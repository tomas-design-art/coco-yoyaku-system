import { useEffect, useState } from 'react';
import { getAuditLogs } from '../../api/client';
import type { AuditLog } from '../../types';
import { extractErrorMessage } from '../../utils/errorUtils';

function formatDateTime(value: string) {
    const d = new Date(value);
    return `${d.getFullYear()}/${String(d.getMonth() + 1).padStart(2, '0')}/${String(d.getDate()).padStart(2, '0')} ${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}:${String(d.getSeconds()).padStart(2, '0')}`;
}

export default function AuditLogViewer() {
    const [rows, setRows] = useState<AuditLog[]>([]);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState<string | null>(null);

    const load = async () => {
        setLoading(true);
        setError(null);
        try {
            const res = await getAuditLogs(300);
            setRows(res.data ?? []);
        } catch (err) {
            setError(extractErrorMessage(err, '監査ログの取得に失敗しました'));
        } finally {
            setLoading(false);
        }
    };

    useEffect(() => {
        load();
    }, []);

    return (
        <div className="max-w-6xl mx-auto p-6">
            <div className="flex items-center justify-between mb-4">
                <h1 className="text-2xl font-bold">監査ログ</h1>
                <button
                    onClick={load}
                    className="px-3 py-2 text-sm rounded bg-blue-600 text-white hover:bg-blue-700 disabled:opacity-50"
                    disabled={loading}
                >
                    再読込
                </button>
            </div>

            {error && (
                <div className="mb-4 p-3 bg-red-50 border border-red-200 rounded text-red-700 text-sm">{error}</div>
            )}

            <div className="bg-white border rounded overflow-auto">
                <table className="min-w-full text-sm">
                    <thead className="bg-gray-50 border-b">
                        <tr>
                            <th className="text-left px-3 py-2 font-semibold text-gray-700 whitespace-nowrap">日時</th>
                            <th className="text-left px-3 py-2 font-semibold text-gray-700 whitespace-nowrap">操作者</th>
                            <th className="text-left px-3 py-2 font-semibold text-gray-700 whitespace-nowrap">操作内容</th>
                            <th className="text-left px-3 py-2 font-semibold text-gray-700 whitespace-nowrap">対象ID</th>
                        </tr>
                    </thead>
                    <tbody>
                        {loading && (
                            <tr>
                                <td colSpan={4} className="px-3 py-4 text-gray-500">読み込み中...</td>
                            </tr>
                        )}
                        {!loading && rows.length === 0 && (
                            <tr>
                                <td colSpan={4} className="px-3 py-4 text-gray-500">ログはまだありません</td>
                            </tr>
                        )}
                        {!loading && rows.map((row) => (
                            <tr key={row.id} className="border-b last:border-b-0 hover:bg-gray-50">
                                <td className="px-3 py-2 whitespace-nowrap">{formatDateTime(row.timestamp)}</td>
                                <td className="px-3 py-2 whitespace-nowrap">{row.operator}</td>
                                <td className="px-3 py-2 whitespace-nowrap">{row.action}</td>
                                <td className="px-3 py-2 whitespace-nowrap">{row.target_id ?? '-'}</td>
                            </tr>
                        ))}
                    </tbody>
                </table>
            </div>
        </div>
    );
}
