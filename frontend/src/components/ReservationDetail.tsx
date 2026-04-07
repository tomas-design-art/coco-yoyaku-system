import { useState, useEffect } from 'react';
import { X, CheckCircle, XCircle, ArrowRightLeft, Clock, Pencil } from 'lucide-react';
import type { Reservation, Practitioner, Patient, Menu } from '../types';
import { STATUS_COLORS, CHANNEL_ICONS, CHANNEL_LABELS } from '../types';
import type { ReservationColor } from '../types';
import {
  confirmReservation, cancelRequest, cancelApprove, changeApprove,
  rejectReservation, updateReservation, getPractitioners, getPatients, getMenus, getSettings,
  getReservationColors,
} from '../api/client';
import { extractErrorMessage } from '../utils/errorUtils';
import { generate5MinOptions } from '../utils/timeUtils';

interface ReservationDetailProps {
  reservation: Reservation;
  onClose: () => void;
  onUpdate: () => void;
  onStartReschedule?: (reservation: Reservation) => void;
}

const STATUS_LABELS: Record<string, string> = {
  PENDING: '仮予約',
  HOLD: '一時確保',
  CONFIRMED: '確定',
  CHANGE_REQUESTED: '変更申請中',
  CANCEL_REQUESTED: 'キャンセル申請中',
  CANCELLED: 'キャンセル済',
  REJECTED: '却下',
  EXPIRED: '期限切れ',
};

export default function ReservationDetail({ reservation, onClose, onUpdate, onStartReschedule }: ReservationDetailProps) {
  const r = reservation;
  const [actionError, setActionError] = useState<string | null>(null);
  const [confirmDialog, setConfirmDialog] = useState<{ message: string; action: () => Promise<unknown>; successMessage: string } | null>(null);
  const [successPopup, setSuccessPopup] = useState<string | null>(null);
  const durationMin = (new Date(r.end_time).getTime() - new Date(r.start_time).getTime()) / 60000;

  const startTime = new Date(r.start_time).toLocaleTimeString('ja-JP', { hour: '2-digit', minute: '2-digit' });
  const endTime = new Date(r.end_time).toLocaleTimeString('ja-JP', { hour: '2-digit', minute: '2-digit' });
  const dateStr = new Date(r.start_time).toLocaleDateString('ja-JP');

  // Edit mode
  const [isEditing, setIsEditing] = useState(false);
  const [practitioners, setPractitioners] = useState<Practitioner[]>([]);
  const [patients, setPatients] = useState<Patient[]>([]);
  const [menus, setMenus] = useState<Menu[]>([]);
  const [timeOptions, setTimeOptions] = useState<string[]>([]);
  const [reservationColors, setReservationColors] = useState<ReservationColor[]>([]);
  const [patientSearch, setPatientSearch] = useState('');

  // Edit form state
  const startDt = new Date(r.start_time);
  const [editPatientId, setEditPatientId] = useState<number | null>(r.patient?.id ?? null);
  const [editPractitionerId, setEditPractitionerId] = useState(r.practitioner_id);
  const [editMenuId, setEditMenuId] = useState<number | null>(r.menu?.id ?? null);
  const [editDate, setEditDate] = useState(startDt.toISOString().split('T')[0]);
  const [editStartTime, setEditStartTime] = useState(
    `${String(startDt.getHours()).padStart(2, '0')}:${String(startDt.getMinutes()).padStart(2, '0')}`
  );
  const [editColorId, setEditColorId] = useState<number | null>(r.color_id);
  const [editNotes, setEditNotes] = useState(
    r.notes?.split('\n').filter(line => !line.includes('から予約変更')).join('\n').trim() || ''
  );
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (isEditing) {
      getPractitioners().then(res => setPractitioners((res.data ?? []).filter(p => p.is_active && p.is_visible))).catch(() => setPractitioners([]));
      getPatients({ page: 1, per_page: 500 }).then(res => setPatients(res.data?.items ?? [])).catch(() => setPatients([]));
      getMenus().then(res => setMenus((res.data ?? []).filter(m => m.is_active))).catch(() => setMenus([]));
      getReservationColors().then(res => setReservationColors(res.data ?? [])).catch(() => setReservationColors([]));
      getSettings().then(res => {
        const settings = res.data ?? [];
        const bhStart = settings.find(s => s.key === 'business_hour_start');
        const bhEnd = settings.find(s => s.key === 'business_hour_end');
        const startH = bhStart?.value ? parseInt(bhStart.value.split(':')[0]) : 9;
        const endH = bhEnd?.value ? parseInt(bhEnd.value.split(':')[0]) : 20;
        setTimeOptions(generate5MinOptions(startH, endH));
      }).catch(() => setTimeOptions(generate5MinOptions()));
    }
  }, [isEditing]);

  // Compute edit end time from menu duration
  const selectedMenu = menus.find(m => m.id === editMenuId);
  const editDuration = selectedMenu ? selectedMenu.duration_minutes : durationMin;
  const computeEndTime = () => {
    const [h, m] = editStartTime.split(':').map(Number);
    const endMin = h * 60 + m + editDuration;
    return `${String(Math.floor(endMin / 60)).padStart(2, '0')}:${String(endMin % 60).padStart(2, '0')}`;
  };

  const filteredPatients = patientSearch.length > 0
    ? patients.filter(p => p.name.includes(patientSearch) || (p.patient_number && p.patient_number.includes(patientSearch)))
    : [];

  const handleSaveEdit = async () => {
    setActionError(null);
    setSaving(true);
    try {
      const endTimeStr = computeEndTime();
      // Preserve change log lines in notes
      const changeLogs = r.notes?.split('\n').filter(line => line.includes('から予約変更')) || [];
      const fullNotes = [...changeLogs, editNotes].filter(Boolean).join('\n') || null;

      await updateReservation(r.id, {
        patient_id: editPatientId,
        practitioner_id: editPractitionerId,
        menu_id: editMenuId,
        color_id: editColorId,
        start_time: `${editDate}T${editStartTime}:00+09:00`,
        end_time: `${editDate}T${endTimeStr}:00+09:00`,
        notes: fullNotes,
      } as Record<string, unknown>);
      setIsEditing(false);
      setSuccessPopup('予約を更新しました');
      onUpdate();
      setTimeout(() => { setSuccessPopup(null); onClose(); }, 1500);
    } catch (err: unknown) {
      setActionError(extractErrorMessage(err, '更新に失敗しました'));
    } finally {
      setSaving(false);
    }
  };

  const handleConfirmedAction = (message: string, action: () => Promise<unknown>, successMessage: string) => {
    setActionError(null);
    setConfirmDialog({ message, action, successMessage });
  };

  const executeConfirmedAction = async () => {
    if (!confirmDialog) return;
    setActionError(null);
    try {
      await confirmDialog.action();
      setConfirmDialog(null);
      setSuccessPopup(confirmDialog.successMessage);
      onUpdate();
      setTimeout(() => {
        setSuccessPopup(null);
        onClose();
      }, 1500);
    } catch (err: unknown) {
      setConfirmDialog(null);
      setActionError(extractErrorMessage(err, 'アクションの実行に失敗しました'));
    }
  };

  // Parse change logs from notes
  const changeLogLines = r.notes?.split('\n').filter(line => line.includes('から予約変更')) || [];

  return (
    <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50">
      <div className="bg-white rounded-lg shadow-xl w-full max-w-md mx-4 max-h-[90vh] overflow-y-auto">
        <div className="flex items-center justify-between p-4 border-b">
          <h3 className="font-semibold">予約詳細</h3>
          <button onClick={onClose} className="p-1 hover:bg-gray-100 rounded"><X size={18} /></button>
        </div>

        <div className="p-4 space-y-3">
          {/* Status badge */}
          <div className="flex items-center gap-2">
            <span
              className="px-2 py-1 rounded text-white text-xs font-medium"
              style={{ backgroundColor: STATUS_COLORS[r.status] }}
            >
              {STATUS_LABELS[r.status] || r.status}
            </span>
            <span className="text-sm">{CHANNEL_ICONS[r.channel]} {CHANNEL_LABELS[r.channel]}</span>
          </div>

          {isEditing ? (
            /* ===== EDIT MODE ===== */
            <div className="space-y-3">
              {/* Patient */}
              <div>
                <label className="text-xs text-gray-500">患者</label>
                <div className="relative">
                  <input
                    type="text"
                    placeholder="患者名 or 番号で検索..."
                    value={patientSearch}
                    onChange={(e) => setPatientSearch(e.target.value)}
                    className="w-full border rounded px-2 py-1 text-sm"
                  />
                  {filteredPatients.length > 0 && (
                    <div className="absolute z-10 w-full bg-white border rounded shadow-lg max-h-32 overflow-y-auto mt-0.5">
                      {filteredPatients.slice(0, 10).map(p => (
                        <button
                          key={p.id}
                          onClick={() => { setEditPatientId(p.id); setPatientSearch(''); }}
                          className="w-full text-left px-2 py-1 text-sm hover:bg-blue-50"
                        >
                          {p.name} {p.patient_number && <span className="text-gray-400">#{p.patient_number}</span>}
                        </button>
                      ))}
                    </div>
                  )}
                </div>
                <p className="text-xs text-gray-600 mt-0.5">
                  選択中: {editPatientId ? (patients.find(p => p.id === editPatientId)?.name || r.patient?.name || `ID:${editPatientId}`) : '飛び込み'}
                  {editPatientId && (
                    <button onClick={() => setEditPatientId(null)} className="ml-2 text-red-400 hover:text-red-600">クリア</button>
                  )}
                </p>
              </div>

              {/* Practitioner */}
              <div>
                <label className="text-xs text-gray-500">施術者</label>
                <select
                  value={editPractitionerId}
                  onChange={(e) => setEditPractitionerId(Number(e.target.value))}
                  className="w-full border rounded px-2 py-1 text-sm"
                >
                  {practitioners.map(p => (
                    <option key={p.id} value={p.id}>{p.name}</option>
                  ))}
                </select>
              </div>

              {/* Menu */}
              <div>
                <label className="text-xs text-gray-500">メニュー</label>
                <select
                  value={editMenuId ?? ''}
                  onChange={(e) => setEditMenuId(e.target.value ? Number(e.target.value) : null)}
                  className="w-full border rounded px-2 py-1 text-sm"
                >
                  <option value="">なし</option>
                  {menus.map(m => (
                    <option key={m.id} value={m.id}>{m.name} ({m.duration_minutes}分)</option>
                  ))}
                </select>
              </div>

              {/* Color */}
              <div>
                <label className="text-xs text-gray-500">予約色</label>
                <select
                  value={editColorId ?? ''}
                  onChange={(e) => setEditColorId(e.target.value ? Number(e.target.value) : null)}
                  className="w-full border rounded px-2 py-1 text-sm"
                >
                  <option value="">なし</option>
                  {reservationColors.map(c => (
                    <option key={c.id} value={c.id}>
                      {c.name}
                    </option>
                  ))}
                </select>
                {editColorId && (
                  <div className="flex items-center gap-1 mt-0.5">
                    <span
                      className="inline-block w-3 h-3 rounded-full"
                      style={{ backgroundColor: reservationColors.find(c => c.id === editColorId)?.color_code || '#ccc' }}
                    />
                    <span className="text-xs text-gray-500">
                      {reservationColors.find(c => c.id === editColorId)?.name}
                    </span>
                  </div>
                )}
              </div>

              {/* Date & Time */}
              <div className="grid grid-cols-2 gap-2">
                <div>
                  <label className="text-xs text-gray-500">日付</label>
                  <input
                    type="date"
                    value={editDate}
                    onChange={(e) => setEditDate(e.target.value)}
                    className="w-full border rounded px-2 py-1 text-sm"
                  />
                </div>
                <div>
                  <label className="text-xs text-gray-500">開始時間</label>
                  <select
                    value={editStartTime}
                    onChange={(e) => setEditStartTime(e.target.value)}
                    className="w-full border rounded px-2 py-1 text-sm"
                  >
                    {timeOptions.map(t => (
                      <option key={t} value={t}>{t}</option>
                    ))}
                  </select>
                </div>
              </div>
              <p className="text-xs text-gray-400">終了: {computeEndTime()}（{editDuration}分間）</p>

              {/* Notes */}
              <div>
                <label className="text-xs text-gray-500">備考</label>
                <textarea
                  value={editNotes}
                  onChange={(e) => setEditNotes(e.target.value)}
                  rows={2}
                  className="w-full border rounded px-2 py-1 text-sm"
                />
              </div>

              {/* Save / Cancel */}
              <div className="flex gap-2 pt-1">
                <button
                  onClick={handleSaveEdit}
                  disabled={saving}
                  className="flex items-center gap-1 px-3 py-1.5 bg-green-500 text-white text-sm rounded hover:bg-green-600 disabled:opacity-50"
                >
                  <CheckCircle size={14} /> {saving ? '保存中...' : '保存'}
                </button>
                <button
                  onClick={() => setIsEditing(false)}
                  className="px-3 py-1.5 bg-gray-200 text-gray-700 text-sm rounded hover:bg-gray-300"
                >
                  キャンセル
                </button>
              </div>
            </div>
          ) : (
            /* ===== VIEW MODE ===== */
            <>
              {/* Patient */}
              <div>
                <span className="text-xs text-gray-500">患者</span>
                <p className="font-medium">{r.patient?.name || '飛び込み'}
                  {r.patient?.patient_number && <span className="text-gray-500 text-sm ml-1">#{r.patient.patient_number}</span>}
                </p>
              </div>

              {/* Practitioner */}
              <div>
                <span className="text-xs text-gray-500">施術者</span>
                <p>{r.practitioner_name || `ID: ${r.practitioner_id}`}</p>
              </div>

              {/* Menu */}
              {r.menu && (
                <div>
                  <span className="text-xs text-gray-500">メニュー</span>
                  <p>{r.menu.name} ({r.menu.duration_minutes}分)</p>
                </div>
              )}

              {/* Time */}
              <div>
                <span className="text-xs text-gray-500">日時</span>
                <p>{dateStr} {startTime} - {endTime}</p>
              </div>

              {/* Change logs */}
              {changeLogLines.length > 0 && (
                <div className="p-2 bg-blue-50 rounded border border-blue-200">
                  <span className="text-xs text-blue-600 font-medium">📋 変更履歴</span>
                  {changeLogLines.map((line, i) => (
                    <p key={i} className="text-xs text-blue-700 mt-0.5">{line}</p>
                  ))}
                </div>
              )}

              {/* Notes (exclude change logs) */}
              {r.notes && (
                <div>
                  <span className="text-xs text-gray-500">備考</span>
                  <p className="text-sm whitespace-pre-wrap">
                    {r.notes.split('\n').filter(line => !line.includes('から予約変更')).join('\n').trim() || ''}
                  </p>
                </div>
              )}

              {/* Conflict note */}
              {r.conflict_note && (
                <div className="p-2 bg-red-50 rounded border border-red-200">
                  <span className="text-xs text-red-600 font-medium">⚠ 競合情報</span>
                  <p className="text-sm text-red-700">{r.conflict_note}</p>
                </div>
              )}
            </>
          )}

          {/* Action buttons */}
          {actionError && (
            <div className="p-3 bg-red-50 border border-red-200 rounded text-red-700 text-sm">{actionError}</div>
          )}
          {!isEditing && (
            <div className="flex flex-wrap gap-2 pt-2 border-t">
              {/* Edit button — available for active statuses */}
              {!['CANCELLED', 'REJECTED', 'EXPIRED'].includes(r.status) && (
                <button
                  onClick={() => setIsEditing(true)}
                  className="flex items-center gap-1 px-3 py-1.5 bg-gray-100 text-gray-700 text-sm rounded hover:bg-gray-200"
                >
                  <Pencil size={14} /> 編集
                </button>
              )}
              {r.status === 'PENDING' && (
                <>
                  <button
                    onClick={() => handleConfirmedAction('この予約を確定しますか？', () => confirmReservation(r.id), '予約を確定しました')}
                    className="flex items-center gap-1 px-3 py-1.5 bg-blue-500 text-white text-sm rounded hover:bg-blue-600"
                  >
                    <CheckCircle size={14} /> 確定する
                  </button>
                  <button
                    onClick={() => handleConfirmedAction('この予約を却下しますか？', () => rejectReservation(r.id), '予約を却下しました')}
                    className="flex items-center gap-1 px-3 py-1.5 bg-red-500 text-white text-sm rounded hover:bg-red-600"
                  >
                    <XCircle size={14} /> 却下する
                  </button>
                </>
              )}
              {r.status === 'CONFIRMED' && (
                <>
                  <button
                    onClick={() => onStartReschedule?.(r)}
                    className="flex items-center gap-1 px-3 py-1.5 bg-blue-100 text-blue-700 text-sm rounded hover:bg-blue-200"
                  >
                    <ArrowRightLeft size={14} /> 予約変更
                  </button>
                  <button
                    onClick={() => handleConfirmedAction('本当にキャンセル申請しますか？', () => cancelRequest(r.id), 'キャンセル申請しました')}
                    className="flex items-center gap-1 px-3 py-1.5 bg-red-100 text-red-700 text-sm rounded hover:bg-red-200"
                  >
                    <XCircle size={14} /> キャンセル申請
                  </button>
                </>
              )}
              {r.status === 'CANCEL_REQUESTED' && (
                <button
                  onClick={() => handleConfirmedAction('キャンセルを承認しますか？', () => cancelApprove(r.id), 'キャンセルを承認しました')}
                  className="flex items-center gap-1 px-3 py-1.5 bg-red-500 text-white text-sm rounded hover:bg-red-600"
                >
                  <CheckCircle size={14} /> キャンセル承認
                </button>
              )}
              {r.status === 'CHANGE_REQUESTED' && (
                <button
                  onClick={() => handleConfirmedAction('変更を承認しますか？', () => changeApprove(r.id), '変更を承認しました')}
                  className="flex items-center gap-1 px-3 py-1.5 bg-blue-500 text-white text-sm rounded hover:bg-blue-600"
                >
                  <ArrowRightLeft size={14} /> 変更承認
                </button>
              )}
              {r.hold_expires_at && r.status === 'HOLD' && (
                <div className="flex items-center gap-1 text-sm text-purple-600">
                  <Clock size={14} /> HOLD期限: {new Date(r.hold_expires_at).toLocaleTimeString('ja-JP', { hour: '2-digit', minute: '2-digit' })}
                </div>
              )}
            </div>
          )}
        </div>
      </div>

      {/* Confirmation dialog */}
      {confirmDialog && (
        <div className="fixed inset-0 bg-black bg-opacity-40 flex items-center justify-center z-[60]">
          <div className="bg-white rounded-lg shadow-2xl p-6 max-w-xs mx-4">
            <p className="text-sm font-medium mb-4">{confirmDialog.message}</p>
            <div className="flex gap-2 justify-end">
              <button
                onClick={() => setConfirmDialog(null)}
                className="px-4 py-2 bg-gray-200 text-gray-700 text-sm rounded hover:bg-gray-300"
              >
                いいえ
              </button>
              <button
                onClick={executeConfirmedAction}
                className="px-4 py-2 bg-blue-500 text-white text-sm rounded hover:bg-blue-600"
              >
                はい
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Success popup */}
      {successPopup && (
        <div className="fixed inset-0 flex items-center justify-center z-[70] pointer-events-none">
          <div className="bg-green-500 text-white px-6 py-3 rounded-lg shadow-2xl flex items-center gap-2 animate-bounce">
            <CheckCircle size={20} />
            <span className="font-medium">{successPopup}</span>
          </div>
        </div>
      )}
    </div>
  );
}
