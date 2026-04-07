import { useState, useEffect } from 'react';
import { X } from 'lucide-react';
import type { Menu, Practitioner, ReservationCreate, Channel, ReservationColor, Patient, BulkReservationResult } from '../../types';
import { getMenus, getPractitioners, createReservation, bulkCreateReservations, getReservationColors, getSettings } from '../../api/client';
import { generate5MinOptions, minutesToTime } from '../../utils/timeUtils';
import { extractErrorMessage } from '../../utils/errorUtils';
import PatientSearch from './PatientSearch';

interface ReservationFormProps {
  isOpen: boolean;
  onClose: () => void;
  onSuccess: () => void;
  initialData?: {
    practitionerId?: number;
    date?: Date;
    startMinutes?: number;
    endMinutes?: number;
  };
}

const channels: { value: Channel; label: string }[] = [
  { value: 'PHONE', label: '📞 電話' },
  { value: 'WALK_IN', label: '🏥 窓口' },
  { value: 'LINE', label: '💬 LINE' },
  { value: 'HOTPEPPER', label: '🔥 HotPepper' },
  { value: 'CHATBOT', label: '🤖 チャットボット' },
];

export default function ReservationForm({ isOpen, onClose, onSuccess, initialData }: ReservationFormProps) {
  const [practitioners, setPractitioners] = useState<Practitioner[]>([]);
  const [menus, setMenus] = useState<Menu[]>([]);
  const [colors, setColors] = useState<ReservationColor[]>([]);
  const [patientId, setPatientId] = useState<number | null>(null);
  const [patientName, setPatientName] = useState('');
  const [practitionerId, setPractitionerId] = useState<number>(0);
  const [menuId, setMenuId] = useState<number | null>(null);
  const [colorId, setColorId] = useState<number | null>(null);
  const [date, setDate] = useState('');
  const [startTime, setStartTime] = useState('09:00');
  const [endTime, setEndTime] = useState('09:30');
  const [channel, setChannel] = useState<Channel>('PHONE');
  const [notes, setNotes] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [timeOptions, setTimeOptions] = useState<string[]>(() => generate5MinOptions());

  // 繰り返し予約
  const [repeatEnabled, setRepeatEnabled] = useState(false);
  const [frequency, setFrequency] = useState<'weekly' | 'biweekly' | 'monthly'>('weekly');
  const [repeatEndMode, setRepeatEndMode] = useState<'date' | 'count'>('count');
  const [repeatEndDate, setRepeatEndDate] = useState('');
  const [repeatCount, setRepeatCount] = useState(4);
  const [bulkResult, setBulkResult] = useState<BulkReservationResult | null>(null);

  useEffect(() => {
    if (isOpen) {
      getPractitioners().then((res) => setPractitioners((res.data ?? []).filter((p) => p.is_active && p.is_visible))).catch(() => setPractitioners([]));
      getMenus().then((res) => setMenus((res.data ?? []).filter((m) => m.is_active))).catch(() => setMenus([]));
      getReservationColors().then((res) => {
        const data = res.data ?? [];
        setColors(data);
        const def = data.find((c) => c.is_default);
        if (def && !colorId) setColorId(def.id);
      }).catch(() => setColors([]));
      getSettings().then((res) => {
        const settings = res.data ?? [];
        const bhStart = settings.find((s) => s.key === 'business_hour_start');
        const bhEnd = settings.find((s) => s.key === 'business_hour_end');
        const startH = bhStart?.value ? parseInt(bhStart.value.split(':')[0], 10) : 9;
        const endH = bhEnd?.value ? parseInt(bhEnd.value.split(':')[0], 10) : 20;
        setTimeOptions(generate5MinOptions(startH, endH));
      }).catch(() => setTimeOptions(generate5MinOptions()));
    }
  }, [isOpen]);

  useEffect(() => {
    if (initialData) {
      if (initialData.practitionerId) setPractitionerId(initialData.practitionerId);
      if (initialData.date) {
        const d = initialData.date;
        setDate(`${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`);
      }
      if (initialData.startMinutes !== undefined) setStartTime(minutesToTime(initialData.startMinutes));
      if (initialData.endMinutes !== undefined) setEndTime(minutesToTime(initialData.endMinutes));
    }
  }, [initialData]);

  // Auto-calculate end time when menu changes + auto-set color from menu tag
  useEffect(() => {
    if (menuId) {
      const menu = menus.find((m) => m.id === menuId);
      if (menu) {
        const [h, m] = startTime.split(':').map(Number);
        const totalMin = h * 60 + m + menu.duration_minutes;
        setEndTime(minutesToTime(totalMin));
        // Auto-set color from menu's tag
        if (menu.color_id) {
          setColorId(menu.color_id);
        }
      }
    }
  }, [menuId, startTime, menus]);

  // 患者選択時にデフォルトメニュー・時間を自動適用
  const handlePatientSelect = (patient: Patient) => {
    setPatientId(patient.id);
    setPatientName(patient.name);
    if (patient.default_menu_id && menus.some((m) => m.id === patient.default_menu_id)) {
      setMenuId(patient.default_menu_id);
    }
    if (patient.default_duration && !menuId) {
      const [h, m] = startTime.split(':').map(Number);
      const totalMin = h * 60 + m + patient.default_duration;
      setEndTime(minutesToTime(totalMin));
    }
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    setBulkResult(null);
    setSubmitting(true);

    try {
      if (repeatEnabled) {
        // 繰り返し予約一括生成
        const [h, m] = startTime.split(':').map(Number);
        const [eh, em] = endTime.split(':').map(Number);
        const durationMinutes = (eh * 60 + em) - (h * 60 + m);
        const bulkData = {
          patient_id: patientId,
          practitioner_id: practitionerId,
          menu_id: menuId,
          color_id: colorId,
          start_time: startTime,
          duration_minutes: durationMinutes,
          channel,
          notes: notes || undefined,
          frequency,
          start_date: date,
          end_date: repeatEndMode === 'date' ? repeatEndDate : undefined,
          count: repeatEndMode === 'count' ? repeatCount : undefined,
        };
        const res = await bulkCreateReservations(bulkData);
        setBulkResult(res.data);
        if (res.data.created_count > 0) {
          onSuccess();
        }
      } else {
        // 通常の単発予約
        const data: ReservationCreate = {
          patient_id: patientId,
          practitioner_id: practitionerId,
          menu_id: menuId,
          color_id: colorId,
          start_time: `${date}T${startTime}:00+09:00`,
          end_time: `${date}T${endTime}:00+09:00`,
          channel,
          notes: notes || undefined,
        };
        await createReservation(data);
        onSuccess();
        onClose();
        // Reset form
        setPatientId(null);
        setPatientName('');
        setMenuId(null);
        setNotes('');
        setRepeatEnabled(false);
        setBulkResult(null);
      }
    } catch (err: unknown) {
      setError(extractErrorMessage(err, '予約の登録に失敗しました'));
    } finally {
      setSubmitting(false);
    }
  };

  if (!isOpen) return null;

  return (
    <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50">
      <div className="bg-white rounded-lg shadow-xl w-full max-w-md mx-4 max-h-[90vh] flex flex-col">
        <div className="flex items-center justify-between p-4 border-b">
          <h2 className="text-lg font-semibold">新規予約登録</h2>
          <button onClick={() => { onClose(); setBulkResult(null); }} className="p-1 hover:bg-gray-100 rounded"><X size={20} /></button>
        </div>

        <form onSubmit={handleSubmit} className="p-4 space-y-4 overflow-y-auto">
          {error && (
            <div className="p-3 bg-red-50 border border-red-200 rounded text-red-700 text-sm">{error}</div>
          )}

          {/* Patient */}
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">患者</label>
            <PatientSearch
              onSelect={handlePatientSelect}
              selectedName={patientName}
            />
          </div>

          {/* Practitioner */}
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">施術者 <span className="text-red-500">*</span></label>
            <select
              value={practitionerId}
              onChange={(e) => setPractitionerId(Number(e.target.value))}
              className="w-full border rounded px-3 py-2 text-sm"
              required
            >
              <option value={0} disabled>選択してください</option>
              {practitioners.map((p) => (
                <option key={p.id} value={p.id}>{p.name}</option>
              ))}
            </select>
          </div>

          {/* Menu */}
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">メニュー</label>
            <select
              value={menuId || ''}
              onChange={(e) => setMenuId(e.target.value ? Number(e.target.value) : null)}
              className="w-full border rounded px-3 py-2 text-sm"
            >
              <option value="">未選択</option>
              {menus.map((m) => (
                <option key={m.id} value={m.id}>
                  {m.name} ({m.duration_minutes}分){m.price ? ` ¥${m.price.toLocaleString()}` : ''}
                </option>
              ))}
            </select>
          </div>

          {/* Date & Time */}
          <div className="grid grid-cols-3 gap-2">
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">日付 <span className="text-red-500">*</span></label>
              <input
                type="date"
                value={date}
                onChange={(e) => setDate(e.target.value)}
                className="w-full border rounded px-3 py-2 text-sm"
                required
              />
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">開始 <span className="text-red-500">*</span></label>
              <select
                value={startTime}
                onChange={(e) => setStartTime(e.target.value)}
                className="w-full border rounded px-3 py-2 text-sm"
                required
              >
                {timeOptions.map((t) => (
                  <option key={t} value={t}>{t}</option>
                ))}
              </select>
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">終了 <span className="text-red-500">*</span></label>
              <select
                value={endTime}
                onChange={(e) => setEndTime(e.target.value)}
                className="w-full border rounded px-3 py-2 text-sm"
                required
              >
                {timeOptions.map((t) => (
                  <option key={t} value={t}>{t}</option>
                ))}
              </select>
            </div>
          </div>
          <p className="text-xs text-gray-500">※メニュー選択で自動計算 / 手動変更可（5分刻み）</p>

          {/* Channel */}
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">チャネル <span className="text-red-500">*</span></label>
            <select
              value={channel}
              onChange={(e) => setChannel(e.target.value as Channel)}
              className="w-full border rounded px-3 py-2 text-sm"
            >
              {channels.map((c) => (
                <option key={c.value} value={c.value}>{c.label}</option>
              ))}
            </select>
          </div>

          {/* Color */}
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">予約色</label>
            <div className="flex flex-wrap gap-2">
              {colors.map((c) => (
                <button
                  key={c.id}
                  type="button"
                  onClick={() => setColorId(c.id)}
                  className={`flex items-center gap-1 px-3 py-1 rounded-full text-xs border-2 transition-colors ${colorId === c.id ? 'border-gray-700 shadow' : 'border-transparent hover:border-gray-300'
                    }`}
                  style={{ backgroundColor: c.color_code + '22', color: c.color_code }}
                >
                  <span className="inline-block w-3 h-3 rounded-full" style={{ backgroundColor: c.color_code }} />
                  {c.name}
                </button>
              ))}
            </div>
          </div>

          {/* Notes */}
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">備考</label>
            <textarea
              value={notes}
              onChange={(e) => setNotes(e.target.value)}
              className="w-full border rounded px-3 py-2 text-sm"
              rows={2}
            />
          </div>

          {/* 繰り返し予約 */}
          <div className="border-t pt-3">
            <label className="flex items-center gap-2 text-sm font-medium text-gray-700 cursor-pointer">
              <input
                type="checkbox"
                checked={repeatEnabled}
                onChange={(e) => { setRepeatEnabled(e.target.checked); setBulkResult(null); }}
                className="rounded"
              />
              繰り返し予約（一括生成）
            </label>
            {repeatEnabled && (
              <div className="mt-2 space-y-2 pl-6">
                <div>
                  <label className="block text-xs text-gray-500 mb-1">頻度</label>
                  <select
                    value={frequency}
                    onChange={(e) => setFrequency(e.target.value as 'weekly' | 'biweekly' | 'monthly')}
                    className="w-full border rounded px-3 py-1.5 text-sm"
                  >
                    <option value="weekly">毎週</option>
                    <option value="biweekly">隔週</option>
                    <option value="monthly">毎月</option>
                  </select>
                </div>
                <div>
                  <label className="block text-xs text-gray-500 mb-1">終了条件</label>
                  <div className="flex gap-3 mb-1">
                    <label className="flex items-center gap-1 text-sm cursor-pointer">
                      <input type="radio" name="repeatEnd" checked={repeatEndMode === 'count'} onChange={() => setRepeatEndMode('count')} />
                      回数指定
                    </label>
                    <label className="flex items-center gap-1 text-sm cursor-pointer">
                      <input type="radio" name="repeatEnd" checked={repeatEndMode === 'date'} onChange={() => setRepeatEndMode('date')} />
                      終了日指定
                    </label>
                  </div>
                  {repeatEndMode === 'count' ? (
                    <div className="flex items-center gap-1">
                      <input
                        type="number"
                        min={2}
                        max={52}
                        value={repeatCount}
                        onChange={(e) => setRepeatCount(Number(e.target.value))}
                        className="w-20 border rounded px-2 py-1.5 text-sm"
                      />
                      <span className="text-sm text-gray-600">回</span>
                    </div>
                  ) : (
                    <input
                      type="date"
                      value={repeatEndDate}
                      onChange={(e) => setRepeatEndDate(e.target.value)}
                      className="w-full border rounded px-3 py-1.5 text-sm"
                      min={date}
                    />
                  )}
                </div>
                <p className="text-xs text-gray-400">※休診日・競合がある日はスキップされます</p>
              </div>
            )}
          </div>

          {/* 一括生成結果 */}
          {bulkResult && (
            <div className={`p-3 rounded text-sm ${bulkResult.created_count > 0 ? 'bg-green-50 border border-green-200 text-green-800' : 'bg-yellow-50 border border-yellow-200 text-yellow-800'}`}>
              <p className="font-medium">{bulkResult.created_count} / {bulkResult.total_requested} 件作成しました</p>
              {(bulkResult.skipped ?? []).length > 0 && (
                <details className="mt-1">
                  <summary className="cursor-pointer text-xs">スキップ: {bulkResult.skipped.length}件</summary>
                  <ul className="mt-1 text-xs space-y-0.5">
                    {(bulkResult.skipped ?? []).map((s, i) => (
                      <li key={i}>{s.date}: {s.reason}</li>
                    ))}
                  </ul>
                </details>
              )}
            </div>
          )}

          {/* Buttons */}
          <div className="flex justify-end gap-2 pt-2">
            <button type="button" onClick={() => { onClose(); setBulkResult(null); }} className="px-4 py-2 text-sm border rounded hover:bg-gray-50">
              {bulkResult ? '閉じる' : 'キャンセル'}
            </button>
            {!bulkResult && (
              <button
                type="submit"
                disabled={submitting || !practitionerId || !date}
                className="px-4 py-2 text-sm bg-blue-500 text-white rounded hover:bg-blue-600 disabled:opacity-50"
              >
                {submitting ? '登録中...' : repeatEnabled ? '一括生成' : '予約登録'}
              </button>
            )}
          </div>
        </form>
      </div>
    </div>
  );
}
