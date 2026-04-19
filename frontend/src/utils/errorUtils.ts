/**
 * APIエラーレスポンスからユーザー向けメッセージを抽出する
 */
export function extractErrorMessage(err: unknown, fallback = '予期しないエラーが発生しました'): string {
    if (!err || typeof err !== 'object') return fallback;

    const axiosErr = err as { response?: { data?: { detail?: unknown }; status?: number }; message?: string };
    const detail = axiosErr.response?.data?.detail;

    if (detail) {
        if (typeof detail === 'string') return detail;
        // 409 conflict with nested object
        if (typeof detail === 'object' && !Array.isArray(detail)) {
            const obj = detail as {
                detail?: string;
                conflicting_reservations?: Array<{ patient_name?: string; start_time?: string; end_time?: string }>;
                patient_conflicts?: Array<{ practitioner_name?: string; start_time?: string; end_time?: string }>;
                alternative_practitioners?: Array<{ practitioner_name?: string; is_available?: boolean }>;
            };
            const parts: string[] = [];
            if (obj.detail) parts.push(obj.detail);
            if (obj.conflicting_reservations && obj.conflicting_reservations.length > 0) {
                const msg = obj.conflicting_reservations
                    .map((c) => {
                        const name = c.patient_name || '不明';
                        const st = c.start_time ? new Date(c.start_time).toLocaleTimeString('ja-JP', { hour: '2-digit', minute: '2-digit' }) : '';
                        const et = c.end_time ? new Date(c.end_time).toLocaleTimeString('ja-JP', { hour: '2-digit', minute: '2-digit' }) : '';
                        return `${name}(${st}-${et})`;
                    })
                    .join(', ');
                parts.push(`競合中の予約: ${msg}`);
            }
            if (obj.patient_conflicts && obj.patient_conflicts.length > 0) {
                const msg = obj.patient_conflicts
                    .map((c) => {
                        const prac = c.practitioner_name || '不明';
                        const st = c.start_time ? new Date(c.start_time).toLocaleTimeString('ja-JP', { hour: '2-digit', minute: '2-digit' }) : '';
                        const et = c.end_time ? new Date(c.end_time).toLocaleTimeString('ja-JP', { hour: '2-digit', minute: '2-digit' }) : '';
                        return `${prac}(${st}-${et})`;
                    })
                    .join(', ');
                parts.push(`患者の重複予約: ${msg}`);
            }
            if (obj.alternative_practitioners && obj.alternative_practitioners.length > 0) {
                const names = obj.alternative_practitioners
                    .map((a) => a.practitioner_name)
                    .filter(Boolean)
                    .join(', ');
                if (names) parts.push(`別の施術者が空いています → ${names} にスライドして予約してください`);
            }
            if (parts.length > 0) return parts.join(' / ');
            return JSON.stringify(detail);
        }
        // 422 validation: array of errors
        if (Array.isArray(detail)) {
            return detail
                .map((e: { msg?: string; loc?: string[] }) => e.msg || JSON.stringify(e))
                .join(' / ');
        }
    }

    // Network or other errors
    if (axiosErr.message) return axiosErr.message;
    return fallback;
}
