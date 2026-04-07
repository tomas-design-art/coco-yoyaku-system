import { useEffect, useMemo, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import type { Menu, WebReserveConflict } from '../types';
import { getMenus, submitWebReserve } from '../api/client';
import { extractErrorMessage } from '../utils/errorUtils';

function toLocalDateInput(iso: string): { date: string; time: string } {
    const d = new Date(iso);
    const yyyy = d.getFullYear();
    const mm = String(d.getMonth() + 1).padStart(2, '0');
    const dd = String(d.getDate()).padStart(2, '0');
    const hh = String(d.getHours()).padStart(2, '0');
    const mi = String(d.getMinutes()).padStart(2, '0');
    return { date: `${yyyy}-${mm}-${dd}`, time: `${hh}:${mi}` };
}

function toJstIso(date: string, time: string): string {
    return `${date}T${time}:00+09:00`;
}

export default function PublicReserve() {
    const [searchParams] = useSearchParams();
    const [menus, setMenus] = useState<Menu[]>([]);
    const [name, setName] = useState('');
    const [phone, setPhone] = useState('');
    const [menuId, setMenuId] = useState<number | null>(null);
    const [duration, setDuration] = useState<number | ''>('');
    const [date, setDate] = useState('');
    const [time, setTime] = useState('');
    const [loading, setLoading] = useState(false);
    const [error, setError] = useState<string | null>(null);
    const [done, setDone] = useState(false);
    const [conflict, setConflict] = useState<WebReserveConflict | null>(null);

    const selectedMenu = useMemo(
        () => menus.find((m) => m.id === menuId) ?? null,
        [menus, menuId],
    );

    useEffect(() => {
        (async () => {
            try {
                const res = await getMenus();
                const active = res.data.filter((m) => m.is_active);
                setMenus(active);

                const qMenu = Number(searchParams.get('menu_id'));
                const qDuration = Number(searchParams.get('duration'));

                if (qMenu && active.some((m) => m.id === qMenu)) {
                    const menu = active.find((m) => m.id === qMenu)!;
                    setMenuId(menu.id);
                    if (menu.is_duration_variable && qDuration) {
                        setDuration(qDuration);
                    } else {
                        setDuration(menu.duration_minutes);
                    }
                }
            } catch (err: unknown) {
                setError(extractErrorMessage(err, 'メニュー取得に失敗しました'));
            }
        })();
    }, [searchParams]);

    useEffect(() => {
        if (!selectedMenu) return;
        if (!selectedMenu.is_duration_variable) {
            setDuration(selectedMenu.duration_minutes);
            return;
        }

        const minDur = selectedMenu.duration_minutes;
        const maxDur = selectedMenu.max_duration_minutes ?? selectedMenu.duration_minutes;
        const curr = Number(duration || 0);
        if (!curr || curr < minDur || curr > maxDur || curr % 10 !== 0) {
            setDuration(minDur);
        }
    }, [selectedMenu, duration]);

    const handleSubmit = async (e: React.FormEvent) => {
        e.preventDefault();
        setError(null);
        setConflict(null);

        if (!menuId || !date || !time) {
            setError('メニューと日時を入力してください');
            return;
        }

        try {
            setLoading(true);
            const res = await submitWebReserve({
                name,
                phone,
                menu_id: menuId,
                desired_datetime: toJstIso(date, time),
                duration: typeof duration === 'number' ? duration : undefined,
            });

            if (res.data.status === 'success') {
                setDone(true);
                return;
            }

            setConflict(res.data as WebReserveConflict);
        } catch (err: unknown) {
            setError(extractErrorMessage(err, '予約送信に失敗しました'));
        } finally {
            setLoading(false);
        }
    };

    if (done) {
        return (
            <div className="min-h-screen bg-slate-50 flex items-center justify-center p-4">
                <div className="max-w-md w-full bg-white rounded-2xl shadow-xl p-8 text-center">
                    <h1 className="text-2xl font-bold text-slate-800 mb-3">ご予約を受け付けました</h1>
                    <p className="text-slate-600">ご来院をお待ちしております。</p>
                </div>
            </div>
        );
    }

    return (
        <div className="min-h-screen bg-gradient-to-b from-cyan-50 to-white py-10 px-4">
            <div className="max-w-xl mx-auto bg-white rounded-2xl shadow-xl p-6 md:p-8">
                <h1 className="text-2xl font-bold text-slate-900 mb-2">Web予約フォーム</h1>
                <p className="text-sm text-slate-600 mb-6">ご希望内容を入力してください。空き枠は自動で確認します。</p>

                {error && <div className="mb-4 rounded-lg bg-red-50 border border-red-200 p-3 text-sm text-red-700">{error}</div>}

                <form onSubmit={handleSubmit} className="space-y-4">
                    <div>
                        <label className="block text-sm font-medium mb-1">お名前</label>
                        <input
                            value={name}
                            onChange={(e) => setName(e.target.value)}
                            className="w-full border rounded-lg px-3 py-2"
                            required
                        />
                    </div>

                    <div>
                        <label className="block text-sm font-medium mb-1">電話番号</label>
                        <input
                            value={phone}
                            onChange={(e) => setPhone(e.target.value)}
                            className="w-full border rounded-lg px-3 py-2"
                            required
                        />
                    </div>

                    <div>
                        <label className="block text-sm font-medium mb-1">メニュー</label>
                        <select
                            value={menuId ?? ''}
                            onChange={(e) => setMenuId(e.target.value ? Number(e.target.value) : null)}
                            className="w-full border rounded-lg px-3 py-2"
                            required
                        >
                            <option value="">選択してください</option>
                            {menus.map((m) => (
                                <option key={m.id} value={m.id}>
                                    {m.name} ({m.duration_minutes}分)
                                </option>
                            ))}
                        </select>
                    </div>

                    {selectedMenu?.is_duration_variable && (
                        <div>
                            <label className="block text-sm font-medium mb-1">施術時間（10分刻み）</label>
                            <input
                                type="number"
                                min={selectedMenu.duration_minutes}
                                max={selectedMenu.max_duration_minutes ?? selectedMenu.duration_minutes}
                                step={10}
                                value={duration}
                                onChange={(e) => setDuration(e.target.value ? Number(e.target.value) : '')}
                                className="w-full border rounded-lg px-3 py-2"
                                required
                            />
                        </div>
                    )}

                    <div className="grid grid-cols-2 gap-3">
                        <div>
                            <label className="block text-sm font-medium mb-1">希望日</label>
                            <input type="date" value={date} onChange={(e) => setDate(e.target.value)} className="w-full border rounded-lg px-3 py-2" required />
                        </div>
                        <div>
                            <label className="block text-sm font-medium mb-1">希望時間</label>
                            <input type="time" value={time} onChange={(e) => setTime(e.target.value)} className="w-full border rounded-lg px-3 py-2" required />
                        </div>
                    </div>

                    <button
                        type="submit"
                        disabled={loading}
                        className="w-full bg-cyan-600 text-white rounded-lg py-2.5 font-medium hover:bg-cyan-700 disabled:opacity-50"
                    >
                        {loading ? '送信中...' : '予約を送信する'}
                    </button>
                </form>

                {conflict && (
                    <div className="mt-6 border-t pt-5">
                        <h2 className="font-semibold text-slate-800 mb-2">その時間は埋まっていました</h2>
                        <p className="text-sm text-slate-600 mb-3">候補から選んで再送できます。</p>
                        <div className="flex flex-wrap gap-2">
                            {conflict.alternatives.map((iso) => {
                                const v = toLocalDateInput(iso);
                                return (
                                    <button
                                        key={iso}
                                        type="button"
                                        onClick={() => {
                                            setDate(v.date);
                                            setTime(v.time);
                                        }}
                                        className="px-3 py-1.5 rounded-full text-sm bg-slate-100 hover:bg-slate-200"
                                    >
                                        {v.date} {v.time}
                                    </button>
                                );
                            })}
                        </div>
                    </div>
                )}
            </div>
        </div>
    );
}
