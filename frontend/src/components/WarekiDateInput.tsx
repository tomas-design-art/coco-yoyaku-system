import { useState, useEffect, useCallback } from 'react';

/**
 * 和暦⇔西暦 切り替え可能な生年月日入力
 * value / onChange は ISO "YYYY-MM-DD" 文字列を入出力する
 */

interface Era {
    name: string;
    startYear: number; // 西暦
    startMonth: number;
    startDay: number;
    endYear: number;
    endMonth: number;
    endDay: number;
}

// 使用頻度順: 昭和 > 平成 > 令和 > 大正
const ERAS: Era[] = [
    { name: '昭和', startYear: 1926, startMonth: 12, startDay: 25, endYear: 1989, endMonth: 1, endDay: 7 },
    { name: '平成', startYear: 1989, startMonth: 1, startDay: 8, endYear: 2019, endMonth: 4, endDay: 30 },
    { name: '令和', startYear: 2019, startMonth: 5, startDay: 1, endYear: 2099, endMonth: 12, endDay: 31 },
    { name: '大正', startYear: 1912, startMonth: 7, startDay: 30, endYear: 1926, endMonth: 12, endDay: 24 },
];

function warekiToSeireki(eraName: string, eraYear: number): number | null {
    const era = ERAS.find((e) => e.name === eraName);
    if (!era) return null;
    return era.startYear + eraYear - 1;
}

function seirekiToWareki(year: number, month: number, day: number): { era: string; year: number } | null {
    const d = new Date(year, month - 1, day);
    for (const era of ERAS) {
        const eraStart = new Date(era.startYear, era.startMonth - 1, era.startDay);
        const eraEnd = new Date(era.endYear, era.endMonth - 1, era.endDay);
        if (d >= eraStart && d <= eraEnd) {
            return { era: era.name, year: year - era.startYear + 1 };
        }
    }
    return null;
}

function getMaxEraYear(eraName: string): number {
    const era = ERAS.find((e) => e.name === eraName);
    if (!era) return 99;
    return era.endYear - era.startYear + 1;
}

function daysInMonth(year: number, month: number): number {
    return new Date(year, month, 0).getDate();
}

interface WarekiDateInputProps {
    value: string;           // "YYYY-MM-DD" or ""
    onChange: (iso: string) => void;
    className?: string;
    onKeyDown?: (e: React.KeyboardEvent) => void;
}

export default function WarekiDateInput({ value, onChange, className, onKeyDown }: WarekiDateInputProps) {
    const [isWareki, setIsWareki] = useState(true);

    // 和暦フィールド
    const [era, setEra] = useState('昭和');
    const [eraYear, setEraYear] = useState('');
    const [month, setMonth] = useState('');
    const [day, setDay] = useState('');

    // 外部 value が変わったら内部状態を同期
    useEffect(() => {
        if (!value) {
            setEraYear('');
            setMonth('');
            setDay('');
            return;
        }
        const parts = value.split('-');
        if (parts.length !== 3) return;
        const [y, m, d] = parts.map(Number);
        setMonth(String(m));
        setDay(String(d));
        const w = seirekiToWareki(y, m, d);
        if (w) {
            setEra(w.era);
            setEraYear(String(w.year));
        } else {
            // 元号範囲外 — 西暦モードにフォールバック
            setIsWareki(false);
        }
    }, [value]);

    // 和暦→ISO変換して親に通知
    const emitWareki = useCallback(
        (eraName: string, ey: string, m: string, d: string) => {
            const eyNum = parseInt(ey, 10);
            const mNum = parseInt(m, 10);
            const dNum = parseInt(d, 10);
            if (!eyNum || !mNum || !dNum) {
                // 不完全 — 空文字を通知
                if (value) onChange('');
                return;
            }
            const seireki = warekiToSeireki(eraName, eyNum);
            if (!seireki) return;
            // 日の上限チェック
            const maxDay = daysInMonth(seireki, mNum);
            const safeDay = Math.min(dNum, maxDay);
            const iso = `${seireki}-${String(mNum).padStart(2, '0')}-${String(safeDay).padStart(2, '0')}`;
            onChange(iso);
        },
        [onChange, value],
    );

    const handleEraChange = (newEra: string) => {
        setEra(newEra);
        emitWareki(newEra, eraYear, month, day);
    };

    const handleEraYearChange = (v: string) => {
        const cleaned = v.replace(/\D/g, '');
        const maxY = getMaxEraYear(era);
        let num = parseInt(cleaned, 10);
        if (num > maxY) num = maxY;
        const final = isNaN(num) ? '' : String(num);
        setEraYear(final);
        emitWareki(era, final, month, day);
    };

    const handleMonthChange = (v: string) => {
        const cleaned = v.replace(/\D/g, '');
        let num = parseInt(cleaned, 10);
        if (num > 12) num = 12;
        const final = isNaN(num) ? '' : String(num);
        setMonth(final);
        emitWareki(era, eraYear, final, day);
    };

    const handleDayChange = (v: string) => {
        const cleaned = v.replace(/\D/g, '');
        let num = parseInt(cleaned, 10);
        if (num > 31) num = 31;
        const final = isNaN(num) ? '' : String(num);
        setDay(final);
        emitWareki(era, eraYear, month, final);
    };

    const inputBase = 'border rounded px-2 py-2 text-sm';

    if (!isWareki) {
        // 西暦モード
        return (
            <div className={className}>
                <div className="flex items-center gap-2">
                    <input
                        type="date"
                        value={value}
                        onChange={(e) => onChange(e.target.value)}
                        onKeyDown={onKeyDown}
                        className={`flex-1 ${inputBase}`}
                    />
                    <button
                        type="button"
                        onClick={() => setIsWareki(true)}
                        className="px-2 py-1 text-xs text-blue-500 hover:text-blue-700 whitespace-nowrap transition-colors"
                    >
                        和暦に戻す
                    </button>
                </div>
            </div>
        );
    }

    // 和暦モード
    return (
        <div className={className}>
            {/* 元号トグルボタン */}
            <div className="flex gap-0.5 mb-1.5">
                {ERAS.map((e) => (
                    <button
                        key={e.name}
                        type="button"
                        onClick={() => handleEraChange(e.name)}
                        className={`px-2.5 py-1 text-sm font-medium rounded transition-colors
                            ${era === e.name
                                ? 'bg-blue-600 text-white shadow-sm'
                                : 'bg-gray-100 text-gray-600 hover:bg-gray-200'
                            }`}
                    >
                        {e.name}
                    </button>
                ))}
                {/* 西暦切替 */}
                <button
                    type="button"
                    onClick={() => setIsWareki(false)}
                    className="ml-auto px-2 py-1 text-xs text-gray-400 hover:text-gray-600 transition-colors"
                >
                    西暦
                </button>
            </div>

            <div className="flex items-center gap-1">
                {/* 年 */}
                <input
                    type="text"
                    inputMode="numeric"
                    value={eraYear}
                    onChange={(e) => handleEraYearChange(e.target.value)}
                    placeholder="年"
                    className={`${inputBase} w-[44px] text-center`}
                    maxLength={2}
                />
                <span className="text-sm text-gray-500">年</span>

                {/* 月 */}
                <input
                    type="text"
                    inputMode="numeric"
                    value={month}
                    onChange={(e) => handleMonthChange(e.target.value)}
                    placeholder="月"
                    className={`${inputBase} w-[38px] text-center`}
                    maxLength={2}
                />
                <span className="text-sm text-gray-500">月</span>

                {/* 日 */}
                <input
                    type="text"
                    inputMode="numeric"
                    value={day}
                    onChange={(e) => handleDayChange(e.target.value)}
                    onKeyDown={onKeyDown}
                    placeholder="日"
                    className={`${inputBase} w-[38px] text-center`}
                    maxLength={2}
                />
                <span className="text-sm text-gray-500">日</span>
            </div>

            {/* 変換結果プレビュー */}
            {value && (
                <p className="text-xs text-gray-400 mt-1">
                    → {value}（西暦）
                </p>
            )}
        </div>
    );
}
