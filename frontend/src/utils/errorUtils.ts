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
            const obj = detail as { detail?: string; conflicting_reservations?: Array<{ patient_name?: string; start_time?: string; end_time?: string }> };
            if (obj.conflicting_reservations) {
                const msg = obj.conflicting_reservations
                    .map((c) => {
                        const name = c.patient_name || '不明';
                        const st = c.start_time ? new Date(c.start_time).toLocaleTimeString('ja-JP', { hour: '2-digit', minute: '2-digit' }) : '';
                        const et = c.end_time ? new Date(c.end_time).toLocaleTimeString('ja-JP', { hour: '2-digit', minute: '2-digit' }) : '';
                        return `${name}(${st}-${et})`;
                    })
                    .join(', ');
                return `予約が競合しています: ${msg}`;
            }
            if (obj.detail) return obj.detail;
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
