import { useState } from 'react';
import { X, RefreshCw, XCircle, Settings } from 'lucide-react';
import { extendSeries, cancelRemainingSeries, declineSeriesExtension, dismissSeriesAlert } from '../../api/client';
import type { SeriesResponse } from '../../types';

interface SeriesExtensionModalProps {
    series: SeriesResponse;
    onClose: () => void;
    onAction: () => void; // refresh after action
}

export default function SeriesExtensionModal({
    series,
    onClose,
    onAction,
}: SeriesExtensionModalProps) {
    const [view, setView] = useState<'choice' | 'extend' | 'modify'>('choice');
    const [extendCount, setExtendCount] = useState(series.remaining_count > 0 ? series.total_created - series.remaining_count : 4);
    const [loading, setLoading] = useState(false);
    const [error, setError] = useState<string | null>(null);

    const handleExtend = async () => {
        setLoading(true);
        setError(null);
        try {
            await extendSeries(series.id, { count: extendCount });
            onAction();
            onClose();
        } catch (e: unknown) {
            const msg = e instanceof Error ? e.message : '延長に失敗しました';
            setError(msg);
        } finally {
            setLoading(false);
        }
    };

    const handleDecline = async () => {
        // 「いいえ（そのまま）」= このシリーズは延長しない旨を確定。
        // バックエンドで is_active=false にして、以降アラートが再掲されないようにする。
        setLoading(true);
        setError(null);
        try {
            await declineSeriesExtension(series.id);
            onAction();
            onClose();
        } catch (e: unknown) {
            const msg = e instanceof Error ? e.message : '確定に失敗しました';
            setError(msg);
        } finally {
            setLoading(false);
        }
    };

    const handleCancelAll = async () => {
        setLoading(true);
        setError(null);
        try {
            await cancelRemainingSeries(series.id);
            onAction();
            onClose();
        } catch (e: unknown) {
            const msg = e instanceof Error ? e.message : 'キャンセルに失敗しました';
            setError(msg);
        } finally {
            setLoading(false);
        }
    };

    const handleDismiss = () => {
        // ✕ボタン: notified_at を NULL に戻し、次回9:00スケジューラまで非表示にする
        dismissSeriesAlert(series.id).catch(() => { /* best-effort */ });
        onClose();
    };

    return (
        <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50">
            <div className="bg-white rounded-lg shadow-xl w-full max-w-md mx-4">
                {/* Header */}
                <div className="flex items-center justify-between px-4 py-3 border-b bg-amber-50">
                    <h3 className="font-bold text-gray-800">
                        繰り返し予約 — 残り{series.remaining_count}回
                    </h3>
                    <button onClick={handleDismiss} className="text-gray-400 hover:text-gray-600" title="閉じる（翌朝9時に再表示）">
                        <X size={20} />
                    </button>
                </div>

                <div className="p-4">
                    {/* Series info */}
                    <div className="mb-4 text-sm text-gray-600 space-y-1">
                        <p>
                            <span className="font-medium">患者:</span> {series.patient_name || '—'}
                        </p>
                        <p>
                            <span className="font-medium">担当:</span> {series.practitioner_name || '—'}
                        </p>
                        <p>
                            <span className="font-medium">メニュー:</span> {series.menu_name || '—'}
                        </p>
                        <p>
                            <span className="font-medium">頻度:</span>{' '}
                            {series.frequency === 'weekly'
                                ? '毎週'
                                : series.frequency === 'biweekly'
                                    ? '隔週'
                                    : '毎月'}
                            {' / '}
                            {series.start_time}〜 ({series.duration_minutes}分)
                        </p>
                    </div>

                    {error && (
                        <div className="mb-3 text-sm text-red-600 bg-red-50 border border-red-200 rounded px-3 py-2">
                            {error}
                        </div>
                    )}

                    {view === 'choice' && (
                        <div className="space-y-3">
                            <p className="text-sm text-gray-700 mb-3">
                                繰り返し予約の残りが{series.remaining_count}回になりました。
                                どうしますか？
                            </p>

                            {/* Option 1: Extend */}
                            <button
                                onClick={() => setView('extend')}
                                className="w-full flex items-center gap-3 px-4 py-3 rounded-lg border-2 border-blue-200 bg-blue-50 hover:bg-blue-100 transition text-left"
                            >
                                <RefreshCw size={20} className="text-blue-600 shrink-0" />
                                <div>
                                    <div className="font-medium text-blue-800">はい（延長する）</div>
                                    <div className="text-xs text-blue-600">同じ設定で繰り返し予約を追加します</div>
                                </div>
                            </button>

                            {/* Option 2: Decline */}
                            <button
                                onClick={handleDecline}
                                disabled={loading}
                                className="w-full flex items-center gap-3 px-4 py-3 rounded-lg border-2 border-gray-200 bg-gray-50 hover:bg-gray-100 transition text-left disabled:opacity-50"
                            >
                                <XCircle size={20} className="text-gray-500 shrink-0" />
                                <div>
                                    <div className="font-medium text-gray-700">いいえ（そのまま）</div>
                                    <div className="text-xs text-gray-500">残り{series.remaining_count}回で終了します</div>
                                </div>
                            </button>

                            {/* Option 3: Modify / Cancel */}
                            <button
                                onClick={handleCancelAll}
                                disabled={loading}
                                className="w-full flex items-center gap-3 px-4 py-3 rounded-lg border-2 border-red-200 bg-red-50 hover:bg-red-100 transition text-left"
                            >
                                <Settings size={20} className="text-red-500 shrink-0" />
                                <div>
                                    <div className="font-medium text-red-700">残りをキャンセル</div>
                                    <div className="text-xs text-red-500">未来の予約をすべてキャンセルします</div>
                                </div>
                            </button>
                        </div>
                    )}

                    {view === 'extend' && (
                        <div className="space-y-4">
                            <p className="text-sm text-gray-700">延長する回数を選択してください（最大13回≒約3か月）</p>
                            <div className="flex items-center gap-2">
                                <input
                                    type="number"
                                    min={1}
                                    max={13}
                                    value={extendCount}
                                    onChange={(e) => setExtendCount(Math.min(13, Math.max(1, Number(e.target.value))))}
                                    className="w-20 border rounded px-2 py-1.5 text-sm"
                                />
                                <span className="text-sm text-gray-600">回</span>
                            </div>
                            <div className="flex gap-2">
                                <button
                                    onClick={() => setView('choice')}
                                    className="flex-1 px-4 py-2 border rounded text-sm text-gray-600 hover:bg-gray-50"
                                >
                                    戻る
                                </button>
                                <button
                                    onClick={handleExtend}
                                    disabled={loading}
                                    className="flex-1 px-4 py-2 bg-blue-600 text-white rounded text-sm hover:bg-blue-700 disabled:opacity-50"
                                >
                                    {loading ? '処理中...' : '延長する'}
                                </button>
                            </div>
                        </div>
                    )}
                </div>
            </div>
        </div>
    );
}
