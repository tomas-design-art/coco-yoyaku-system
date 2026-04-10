import { useState, useEffect, useMemo, useCallback, useRef } from 'react';
import { ChevronLeft, ChevronRight } from 'lucide-react';
import type { Practitioner, Reservation, ReservationColor, WeeklySchedule, PractitionerDayStatus, BusinessHoursDay } from '../../types';
import { CHANNEL_ICONS } from '../../types';
import { generateTimeSlots, dateToMinutes, DAY_START, DAY_END, SLOT_INTERVAL, formatDate, getWeekDates, WEEKDAY_LABELS, getTodayJST, getNowJSTMinutes, timeToMinutes } from '../../utils/timeUtils';
import { getPractitioners, getReservations, getReservationColors, getSettings, getWeeklySchedules, getScheduleStatus, getBusinessHoursRange } from '../../api/client';
import DragSelect from './DragSelect';

const SLOT_HEIGHT = 20;
const TIME_COL_WIDTH = 60;
const WEEK_PRACTITIONER_MIN_WIDTH = 64;
const HEADER_HEIGHT = 32;
const WEEK_HEADER_HEIGHT = 52; // date line + practitioner names line

interface TimeTableProps {
  onSlotClick: (practitionerId: number, startMinutes: number, date: Date) => void;
  onDragSelect: (practitionerId: number, startMinutes: number, endMinutes: number, date: Date) => void;
  onReservationClick: (reservation: Reservation) => void;
  refreshKey: number;
  reschedulingReservation?: Reservation | null;
  onRescheduleSlotClick?: (practitionerId: number, startMinutes: number, date: Date) => void;
  onCancelReschedule?: () => void;
  isFullscreenMode?: boolean;
  onToggleFullscreen?: () => void;
  fullscreenRightControls?: React.ReactNode;
}

export default function TimeTable({ onSlotClick, onDragSelect, onReservationClick, refreshKey, reschedulingReservation, onRescheduleSlotClick, onCancelReschedule, isFullscreenMode = false, onToggleFullscreen, fullscreenRightControls }: TimeTableProps) {
  const [allPractitioners, setAllPractitioners] = useState<Practitioner[]>([]);
  const [reservations, setReservations] = useState<Reservation[]>([]);
  const [colors, setColors] = useState<ReservationColor[]>([]);
  const [currentDate, setCurrentDate] = useState(() => getTodayJST());
  const [viewMode, setViewMode] = useState<'day' | 'week'>('week');
  const [enabledPractitionerIds, setEnabledPractitionerIds] = useState<Set<number>>(new Set());
  const [nowMinutes, setNowMinutes] = useState<number>(getNowJSTMinutes);
  const [dayStart, setDayStart] = useState(DAY_START);
  const [dayEnd, setDayEnd] = useState(DAY_END);
  const [weeklySchedules, setWeeklySchedules] = useState<WeeklySchedule[]>([]);
  const [practitionerStatuses, setPractitionerStatuses] = useState<PractitionerDayStatus[]>([]);
  const [businessHours, setBusinessHours] = useState<BusinessHoursDay[]>([]);
  const gridRef = useRef<HTMLDivElement>(null);

  // 営業時間に基づく動的スロット
  const slots = useMemo(() => generateTimeSlots(dayStart, dayEnd), [dayStart, dayEnd]);

  // visible & active practitioners only
  const visiblePractitioners = useMemo(
    () => allPractitioners.filter((p) => p.is_active && p.is_visible),
    [allPractitioners]
  );

  // practitioners that are toggled ON
  const activePractitioners = useMemo(
    () => visiblePractitioners.filter((p) => enabledPractitionerIds.has(p.id)),
    [visiblePractitioners, enabledPractitionerIds]
  );

  // 1分ごとに現在時刻を更新
  useEffect(() => {
    const timer = setInterval(() => setNowMinutes(getNowJSTMinutes()), 60_000);
    return () => clearInterval(timer);
  }, []);

  const weekDates = useMemo(() => getWeekDates(currentDate), [currentDate]);

  const defaultColorCode = useMemo(() => {
    const def = colors.find(c => c.is_default);
    return def?.color_code || '#3B82F6';
  }, [colors]);

  const getBlockColor = useCallback((r: Reservation): string => {
    if (r.conflict_note) return '#DC2626';
    if (r.status === 'CANCEL_REQUESTED') return '#9CA3AF';
    if (r.status === 'CHANGE_REQUESTED') return '#EAB308';
    if (r.status === 'HOLD') return '#8B5CF6';
    if (r.status === 'PENDING') return '#EAB308';
    if (r.color?.color_code) return r.color.color_code;
    if (r.channel === 'HOTPEPPER' && r.status === 'CONFIRMED') return '#10B981';
    return defaultColorCode;
  }, [defaultColorCode]);

  const getBlockExtraStyle = useCallback((r: Reservation): React.CSSProperties => {
    if (r.status === 'CANCEL_REQUESTED') {
      return { opacity: 0.7, textDecoration: 'line-through', border: '1.5px dashed #6B7280' };
    }
    return {};
  }, []);

  useEffect(() => {
    getPractitioners().then((res) => {
      const all = res.data ?? [];
      setAllPractitioners(all);
      const visible = all.filter((p) => p.is_active && p.is_visible);
      // 初回: 全員ONにする (既にセット済みならスキップ)
      setEnabledPractitionerIds((prev) => {
        if (prev.size > 0) return prev;
        return new Set(visible.map((p) => p.id));
      });
    }).catch(() => setAllPractitioners([]));
    getReservationColors().then((res) => setColors(res.data ?? [])).catch(() => setColors([]));
    // 営業時間設定を取得
    getSettings().then((res) => {
      const settings = res.data ?? [];
      const bhStart = settings.find((s) => s.key === 'business_hour_start');
      const bhEnd = settings.find((s) => s.key === 'business_hour_end');
      if (bhStart?.value) setDayStart(timeToMinutes(bhStart.value));
      if (bhEnd?.value) setDayEnd(timeToMinutes(bhEnd.value));
    }).catch(() => { });
    // 院営業スケジュールを取得
    getWeeklySchedules().then((res) => setWeeklySchedules(res.data ?? [])).catch(() => { });
  }, [refreshKey]);

  const activePractitionerIds = useMemo(
    () => activePractitioners.map((p) => p.id).join(','),
    [activePractitioners]
  );

  useEffect(() => {
    const startDate = viewMode === 'day' ? currentDate : weekDates[0];
    const endDate = viewMode === 'day' ? currentDate : weekDates[6];
    getReservations({
      start_date: formatDate(startDate),
      end_date: formatDate(endDate),
    }).then((res) => setReservations(res.data ?? [])).catch(() => setReservations([]));

    // 職員勤務スケジュールステータスを取得
    if (activePractitionerIds) {
      getScheduleStatus({
        practitioner_ids: activePractitionerIds,
        start_date: formatDate(startDate),
        end_date: formatDate(endDate),
      }).then((res) => setPractitionerStatuses(res.data ?? [])).catch(() => { });
    }

    // 解決済み営業時間（祝日・DateOverride反映）を取得
    getBusinessHoursRange({
      start_date: formatDate(startDate),
      end_date: formatDate(endDate),
    }).then((res) => setBusinessHours(res.data ?? [])).catch(() => { });
  }, [currentDate, viewMode, weekDates, refreshKey, activePractitionerIds]);

  // 施術者トグル
  const togglePractitioner = (id: number) => {
    setEnabledPractitionerIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) {
        if (next.size <= 1) return prev; // 最低1人はON
        next.delete(id);
      } else {
        next.add(id);
      }
      return next;
    });
  };

  // 週表示でも全アクティブ施術者を表示（横スクロールで対応）
  const weekVisiblePractitioners = activePractitioners;

  const goToday = () => setCurrentDate(getTodayJST());
  const goPrev = () => {
    const d = new Date(currentDate);
    d.setDate(d.getDate() - (viewMode === 'day' ? 1 : 7));
    setCurrentDate(d);
  };
  const goNext = () => {
    const d = new Date(currentDate);
    d.setDate(d.getDate() + (viewMode === 'day' ? 1 : 7));
    setCurrentDate(d);
  };

  const getReservationsForColumn = useCallback(
    (practitionerId: number, date: Date) => {
      const dateStr = formatDate(date);
      return reservations.filter((r) => {
        const rDate = r.start_time.split('T')[0];
        return r.practitioner_id === practitionerId && rDate === dateStr
          && !['CANCELLED', 'REJECTED', 'EXPIRED'].includes(r.status);
      });
    },
    [reservations]
  );

  const headerLabel = viewMode === 'day'
    ? `${currentDate.getFullYear()}年${currentDate.getMonth() + 1}月${currentDate.getDate()}日(${WEEKDAY_LABELS[currentDate.getDay()]})`
    : `${weekDates[0].getMonth() + 1}/${weekDates[0].getDate()} 〜 ${weekDates[6].getMonth() + 1}/${weekDates[6].getDate()}`;
  const compactHeaderLabel = viewMode === 'day'
    ? `${currentDate.getMonth() + 1}/${currentDate.getDate()}`
    : (weekDates[0].getMonth() === weekDates[6].getMonth()
      ? `${weekDates[0].getMonth() + 1}/${weekDates[0].getDate()}-${weekDates[6].getDate()}`
      : `${weekDates[0].getMonth() + 1}/${weekDates[0].getDate()}-${weekDates[6].getMonth() + 1}/${weekDates[6].getDate()}`);

  // 日表示の施術者列最大幅
  const dayColMaxWidth = activePractitioners.length === 1 ? 600 : activePractitioners.length === 2 ? 400 : undefined;

  // ----- 曜日スケジュール / 営業時間からオーバーレイを生成 -----
  const getBusinessHoursForDate = useCallback((date: Date): BusinessHoursDay | undefined => {
    const dateStr = formatDate(date);
    return businessHours.find((bh) => bh.date === dateStr);
  }, [businessHours]);

  const getScheduleForDate = useCallback((date: Date): WeeklySchedule | undefined => {
    // fallback for case where businessHours not yet loaded
    const dow = date.getDay();
    return weeklySchedules.find((s) => s.day_of_week === dow);
  }, [weeklySchedules]);

  // ----- 施術者休みチェック -----
  const getPractitionerDayOff = useCallback((practitionerId: number, date: Date): PractitionerDayStatus | null => {
    const dateStr = formatDate(date);
    const status = practitionerStatuses.find(
      (s) => s.practitioner_id === practitionerId && s.date === dateStr
    );
    if (status && !status.is_working) return status;
    return null;
  }, [practitionerStatuses]);

  // ----- 施術者の時間帯休みを取得 -----
  const getUnavailableTimesForColumn = useCallback((practitionerId: number, date: Date) => {
    const dateStr = formatDate(date);
    const status = practitionerStatuses.find(
      (s) => s.practitioner_id === practitionerId && s.date === dateStr
    );
    return status?.unavailable_times || [];
  }, [practitionerStatuses]);

  const renderScheduleOverlay = useCallback((date: Date, headerH: number, _totalHeight: number) => {
    // 解決済み営業時間を優先、なければ weeklySchedule にフォールバック
    const bh = getBusinessHoursForDate(date);
    const schedule = getScheduleForDate(date);

    const isOpen = bh ? bh.is_open : (schedule ? schedule.is_open : true);
    const openTime = bh?.open_time ?? schedule?.open_time;
    const closeTime = bh?.close_time ?? schedule?.close_time;
    const label = bh?.label;
    const source = bh?.source;

    if (!isOpen) {
      // 休診日：全面オーバーレイ
      const displayLabel = label || (source === 'holiday' ? '祝日休診' : '休診日');
      return (
        <div
          className="absolute inset-0 flex items-center justify-center pointer-events-none"
          style={{ top: headerH, bottom: 0, backgroundColor: source === 'holiday' ? 'rgba(239,68,68,0.12)' : 'rgba(209,213,219,0.5)', zIndex: 3 }}
        >
          <span className={`font-bold text-sm bg-white/80 px-2 py-1 rounded ${source === 'holiday' ? 'text-red-500' : 'text-gray-500'}`}>{displayLabel}</span>
        </div>
      );
    }

    if (!openTime || !closeTime) return null;

    // 時短日：営業時間外の部分にオーバーレイ
    const [openH, openM] = openTime.split(':').map(Number);
    const [closeH, closeM] = closeTime.split(':').map(Number);
    const openMin = openH * 60 + openM;
    const closeMin = closeH * 60 + closeM;
    const overlays: React.ReactNode[] = [];

    // 祝日/オーバーライドでの時短営業ラベル
    if (label && isOpen) {
      overlays.push(
        <div key="label" className="absolute left-0 right-0 text-center pointer-events-none" style={{ top: headerH - 2, zIndex: 5 }}>
          <span className="text-xs text-orange-600 bg-orange-50/90 px-1 rounded">{label}</span>
        </div>
      );
    }

    // 営業開始前
    if (openMin > dayStart) {
      const topPx = headerH;
      const heightPx = ((openMin - dayStart) / SLOT_INTERVAL) * SLOT_HEIGHT;
      overlays.push(
        <div
          key="before"
          className="absolute left-0 right-0 flex items-center justify-center pointer-events-none"
          style={{ top: topPx, height: heightPx, backgroundColor: 'rgba(209,213,219,0.45)', zIndex: 3 }}
        >
          <span className="text-gray-400 text-xs bg-white/70 px-1 rounded">営業時間外</span>
        </div>
      );
    }

    // 営業終了後
    if (closeMin < dayEnd) {
      const topPx = ((closeMin - dayStart) / SLOT_INTERVAL) * SLOT_HEIGHT + headerH;
      const heightPx = ((dayEnd - closeMin) / SLOT_INTERVAL) * SLOT_HEIGHT;
      overlays.push(
        <div
          key="after"
          className="absolute left-0 right-0 flex items-center justify-center pointer-events-none"
          style={{ top: topPx, height: heightPx, backgroundColor: 'rgba(209,213,219,0.45)', zIndex: 3 }}
        >
          <span className="text-gray-400 text-xs bg-white/70 px-1 rounded">営業時間外</span>
        </div>
      );
    }

    return overlays.length > 0 ? <>{overlays}</> : null;
  }, [getBusinessHoursForDate, getScheduleForDate, dayStart, dayEnd]);

  // ----- レンダリング用ヘルパー -----
  const isRescheduling = !!reschedulingReservation;

  const renderColumn = (practitionerId: number, date: Date, headerH: number) => {
    const dayOff = getPractitionerDayOff(practitionerId, date);
    const unavailableTimes = getUnavailableTimesForColumn(practitionerId, date);
    return (
      <>
        {dayOff ? (
          /* 休みの施術者: グレーアウト＋クリック無効 */
          <div
            className="absolute inset-0 flex items-center justify-center"
            style={{
              top: headerH,
              bottom: 0,
              zIndex: 4,
              background: 'repeating-linear-gradient(45deg, transparent, transparent 6px, rgba(156,163,175,0.2) 6px, rgba(156,163,175,0.2) 8px)',
              backgroundColor: 'rgba(209,213,219,0.4)',
            }}
            title={dayOff.reason ? `休み: ${dayOff.reason}` : '休み'}
          >
            <span className="text-gray-500 font-bold text-xs bg-white/80 px-2 py-1 rounded shadow-sm">
              {dayOff.reason || '休み'}
            </span>
          </div>
        ) : (
          <DragSelect
            slots={slots}
            slotHeight={SLOT_HEIGHT}
            onSlotClick={(minutes) => {
              if (isRescheduling && onRescheduleSlotClick) {
                onRescheduleSlotClick(practitionerId, minutes, date);
              } else {
                onSlotClick(practitionerId, minutes, date);
              }
            }}
            onDragSelect={(startMin, endMin) => {
              if (isRescheduling && onRescheduleSlotClick) {
                onRescheduleSlotClick(practitionerId, startMin, date);
              } else {
                onDragSelect(practitionerId, startMin, endMin, date);
              }
            }}
          />
        )}
        {/* 時間帯休みオーバーレイ */}
        {!dayOff && unavailableTimes.map((ut) => {
          const [sh, sm] = ut.start_time.split(':').map(Number);
          const [eh, em] = ut.end_time.split(':').map(Number);
          const startMin = sh * 60 + sm;
          const endMin = eh * 60 + em;
          const top = ((startMin - dayStart) / SLOT_INTERVAL) * SLOT_HEIGHT + headerH;
          const height = ((endMin - startMin) / SLOT_INTERVAL) * SLOT_HEIGHT;
          return (
            <div
              key={`ut-${ut.id}`}
              className="absolute left-0 right-0 flex items-center justify-center pointer-events-none"
              style={{
                top,
                height: Math.max(height, SLOT_HEIGHT),
                zIndex: 4,
                background: 'repeating-linear-gradient(45deg, transparent, transparent 4px, rgba(251,191,36,0.15) 4px, rgba(251,191,36,0.15) 6px)',
                backgroundColor: 'rgba(251,191,36,0.18)',
              }}
              title={ut.reason || '時間帯休み'}
            >
              <span className="text-amber-600 font-bold text-xs bg-white/80 px-1 py-0.5 rounded shadow-sm truncate" style={{ fontSize: 9 }}>
                {ut.reason || '休み'}
              </span>
            </div>
          );
        })}
        {getReservationsForColumn(practitionerId, date).map((r) => {
          const startMin = dateToMinutes(r.start_time);
          const endMin = dateToMinutes(r.end_time);
          const top = ((startMin - dayStart) / SLOT_INTERVAL) * SLOT_HEIGHT;
          const height = ((endMin - startMin) / SLOT_INTERVAL) * SLOT_HEIGHT;
          const isTarget = isRescheduling && reschedulingReservation?.id === r.id;
          return (
            <div
              key={r.id}
              className={`absolute left-0.5 right-0.5 rounded px-1 text-white overflow-hidden shadow-sm ${isTarget ? 'ring-2 ring-blue-400 animate-pulse pointer-events-none' : isRescheduling ? '' : 'cursor-pointer hover:opacity-90'}`}
              style={{
                top: top + headerH,
                height: Math.max(height, SLOT_HEIGHT),
                backgroundColor: getBlockColor(r),
                zIndex: isTarget ? 1 : 2,
                fontSize: 10,
                lineHeight: '14px',
                ...getBlockExtraStyle(r),
                ...(isRescheduling && !isTarget ? { opacity: 0.6 } : {}),
              }}
              onClick={(e) => { e.stopPropagation(); if (!isRescheduling) onReservationClick(r); }}
            >
              <div className="flex items-center gap-0.5 truncate">
                <span>{CHANNEL_ICONS[r.channel]}</span>
                <span className="font-medium truncate">{r.patient?.name || '飛び込み'}</span>
              </div>
              {height >= SLOT_HEIGHT * 2 && (
                <div className="truncate opacity-90">{r.menu?.name || ''}</div>
              )}
            </div>
          );
        })}
        {/* 現在時刻インジケーター */}
        {formatDate(date) === formatDate(getTodayJST()) &&
          nowMinutes >= dayStart && nowMinutes <= dayEnd && (
            <div
              className="absolute left-0 right-0 pointer-events-none"
              style={{
                top: ((nowMinutes - dayStart) / SLOT_INTERVAL) * SLOT_HEIGHT + headerH,
                zIndex: 6,
              }}
            >
              <div style={{ position: 'absolute', left: 0, top: -4, width: 8, height: 8, borderRadius: '50%', backgroundColor: '#EF4444' }} />
              <div style={{ height: 2, backgroundColor: '#EF4444', marginLeft: 8 }} />
            </div>
          )}
      </>
    );
  };

  return (
    <div className="flex flex-col h-full">
      {/* Reschedule mode banner */}
      {isRescheduling && reschedulingReservation && (
        <div className="flex items-center justify-between px-4 py-2 bg-blue-50 border-b border-blue-200">
          <div className="flex items-center gap-2 text-blue-800 text-sm">
            <span className="text-lg">📅</span>
            <span className="font-semibold">予約変更中:</span>
            <span>{reschedulingReservation.patient?.name || '飛び込み'}</span>
            <span className="text-blue-600">
              {reschedulingReservation.menu?.name || ''}
              ({Math.round((new Date(reschedulingReservation.end_time).getTime() - new Date(reschedulingReservation.start_time).getTime()) / 60000)}分)
            </span>
            <span className="text-blue-500">→ 空き枠をクリックして変更先を選択</span>
          </div>
          <button
            onClick={onCancelReschedule}
            className="px-3 py-1 text-sm bg-gray-200 text-gray-700 rounded hover:bg-gray-300"
          >
            キャンセル
          </button>
        </div>
      )}

      {/* Header: navigation + view toggle + practitioner toggles — single row */}
      <div className="flex flex-col md:flex-row md:items-center px-2 md:px-4 py-1.5 md:py-2 bg-white border-b gap-1.5 md:gap-2 min-h-[40px] md:min-h-[44px]">
        <div className="flex items-center justify-between md:justify-start gap-1 md:gap-2 shrink-0 min-w-0">
          <button onClick={goPrev} className="p-1 hover:bg-gray-100 rounded"><ChevronLeft size={18} /></button>
          <span className="font-semibold text-xs sm:text-sm md:text-lg min-w-[92px] sm:min-w-[130px] md:min-w-[200px] text-center truncate leading-none">
            <span className="sm:hidden">{compactHeaderLabel}</span>
            <span className="hidden sm:inline">{headerLabel}</span>
          </span>
          <button onClick={goNext} className="p-1 hover:bg-gray-100 rounded"><ChevronRight size={18} /></button>
          <button onClick={goToday} className="ml-1 md:ml-2 px-2 md:px-3 py-1 text-xs md:text-sm bg-blue-500 text-white rounded hover:bg-blue-600">今日</button>
        </div>
        <div className="hidden md:flex flex-1" />
        <div className="flex items-center gap-1 shrink-0 flex-wrap md:flex-nowrap">
          <button onClick={() => setViewMode('day')} className={`px-2 md:px-3 py-1 text-xs md:text-sm rounded whitespace-nowrap ${viewMode === 'day' ? 'bg-blue-500 text-white' : 'bg-gray-200'}`}>日</button>
          <button onClick={() => setViewMode('week')} className={`px-2 md:px-3 py-1 text-xs md:text-sm rounded whitespace-nowrap ${viewMode === 'week' ? 'bg-blue-500 text-white' : 'bg-gray-200'}`}>週</button>
          {visiblePractitioners.map((p) => {
            const on = enabledPractitionerIds.has(p.id);
            return (
              <button
                key={p.id}
                onClick={() => togglePractitioner(p.id)}
                className={`px-1.5 sm:px-2 py-1 text-[10px] sm:text-[11px] md:text-xs rounded-full border transition-colors whitespace-nowrap ${on
                  ? 'bg-blue-500 text-white border-blue-500'
                  : 'bg-white text-gray-500 border-gray-300 hover:border-gray-400'
                  }`}
                title={p.name}
              >
                <span className="sm:hidden">{p.name.slice(0, 2)}</span>
                <span className="hidden sm:inline">{p.name}</span>
              </button>
            );
          })}
          {onToggleFullscreen && !isFullscreenMode && (
            <button
              onClick={onToggleFullscreen}
              className="px-2 md:px-3 py-1 text-xs md:text-sm rounded whitespace-nowrap bg-indigo-500 text-white hover:bg-indigo-600"
              title="タイムテーブル全画面表示"
            >
              全画面
            </button>
          )}
          {fullscreenRightControls}
        </div>
      </div>

      {/* Grid */}
      <div className="flex-1 overflow-auto" ref={gridRef}>
        {viewMode === 'day' ? (
          /* ===== DAY VIEW ===== */
          <div className="flex min-w-max">
            {/* Time labels */}
            <div
              className="sticky left-0 z-40 bg-white shrink-0"
              style={{ width: TIME_COL_WIDTH, minWidth: TIME_COL_WIDTH, borderRight: '1.5px solid #374151' }}
            >
              <div style={{ height: HEADER_HEIGHT }} className="sticky top-0 z-30 border-b bg-gray-50" />
              {slots.map((slot) => {
                const nextMin = slot.minutes + SLOT_INTERVAL;
                const isHour = slot.minutes % 60 === 0;
                let borderStyle: string;
                if (nextMin % 60 === 0) {
                  borderStyle = '2px solid #6b7280';
                } else if (nextMin % 30 === 0) {
                  borderStyle = '1.5px solid #b0b7c0';
                } else if (nextMin % 15 === 0) {
                  borderStyle = '1px solid #d1d5db';
                } else {
                  borderStyle = '0.5px solid #e5e7eb';
                }
                const showLabel = slot.minutes % 30 === 0;
                return (
                  <div
                    key={slot.minutes}
                    className={`flex items-center justify-end pr-2 ${isHour ? 'text-sm text-gray-900 font-bold' : showLabel ? 'text-xs text-gray-700 font-medium' : slot.minutes % 15 === 0 ? 'text-xs text-gray-400' : 'text-xs text-transparent'}`}
                    style={{ height: SLOT_HEIGHT, borderBottom: borderStyle }}
                  >
                    {slot.minutes % 15 === 0 ? slot.label : '.'}
                  </div>
                );
              })}
            </div>

            {/* Day columns — one per practitioner */}
            {activePractitioners.length === 0 && (
              <div className="flex-1 flex items-center justify-center p-12 text-gray-400 text-sm">施術者データがありません</div>
            )}
            {activePractitioners.map((p, pi) => (
              <div
                key={`day-${p.id}`}
                className="relative"
                style={{ minWidth: 150, flex: 1, maxWidth: dayColMaxWidth, borderRight: pi < activePractitioners.length - 1 ? '1px dashed #d1d5db' : 'none' }}
              >
                <div
                  style={{ height: HEADER_HEIGHT }}
                  className="flex items-center justify-center text-sm font-medium bg-gray-50 border-b sticky top-0 z-[15]"
                >
                  {p.name}
                </div>
                {renderColumn(p.id, currentDate, HEADER_HEIGHT)}
                {renderScheduleOverlay(currentDate, HEADER_HEIGHT, slots.length * SLOT_HEIGHT)}
              </div>
            ))}
          </div>
        ) : (
          /* ===== WEEK VIEW ===== */
          <div className="flex min-w-max">
            {/* Time labels */}
            <div
              className="sticky left-0 z-40 bg-white shrink-0"
              style={{ width: TIME_COL_WIDTH, minWidth: TIME_COL_WIDTH, borderRight: '1.5px solid #374151' }}
            >
              <div style={{ height: WEEK_HEADER_HEIGHT }} className="sticky top-0 z-30 border-b bg-gray-50" />
              {slots.map((slot) => {
                const nextMin = slot.minutes + SLOT_INTERVAL;
                const isHour = slot.minutes % 60 === 0;
                let borderStyle: string;
                if (nextMin % 60 === 0) {
                  borderStyle = '2px solid #6b7280';
                } else if (nextMin % 30 === 0) {
                  borderStyle = '1.5px solid #b0b7c0';
                } else if (nextMin % 15 === 0) {
                  borderStyle = '1px solid #d1d5db';
                } else {
                  borderStyle = '0.5px solid #e5e7eb';
                }
                const showLabel = slot.minutes % 30 === 0;
                return (
                  <div
                    key={slot.minutes}
                    className={`flex items-center justify-end pr-2 ${isHour ? 'text-sm text-gray-900 font-bold' : showLabel ? 'text-xs text-gray-700 font-medium' : slot.minutes % 15 === 0 ? 'text-xs text-gray-400' : 'text-xs text-transparent'}`}
                    style={{ height: SLOT_HEIGHT, borderBottom: borderStyle }}
                  >
                    {slot.minutes % 15 === 0 ? slot.label : '.'}
                  </div>
                );
              })}
            </div>

            {/* Week columns — one per day, sub-columns per practitioner */}
            {weekDates.map((date, di) => {
              const isToday = formatDate(date) === formatDate(getTodayJST());
              return (
                <div key={`week-${di}`} className="relative" style={{ flex: 1, minWidth: weekVisiblePractitioners.length * WEEK_PRACTITIONER_MIN_WIDTH, borderRight: '1.5px solid #1f2937' }}>
                  {/* Date + Practitioner headers — sticky top */}
                  <div className={`sticky top-0 z-[15] ${isToday ? 'bg-blue-50' : 'bg-gray-50'}`} style={{ height: WEEK_HEADER_HEIGHT }}>
                    {/* Date header */}
                    <div
                      className={`text-center text-xs font-semibold border-b px-1 ${isToday ? 'text-blue-700' : 'text-gray-700'}`}
                      style={{ height: 20, lineHeight: '20px' }}
                    >
                      {date.getMonth() + 1}/{date.getDate()}({WEEKDAY_LABELS[date.getDay()]})
                    </div>
                    {/* Practitioner sub-column headers */}
                    <div className="flex border-b" style={{ height: WEEK_HEADER_HEIGHT - 20 }}>
                      {weekVisiblePractitioners.map((p) => (
                        <div
                          key={p.id}
                          className={`flex-1 flex items-center justify-center text-xs text-gray-600 last:border-r-0 truncate px-0.5 ${isToday ? 'bg-blue-50' : 'bg-gray-50'}`}
                          style={{ minWidth: WEEK_PRACTITIONER_MIN_WIDTH, borderRight: '1px dashed #d1d5db' }}
                        >
                          {p.name}
                        </div>
                      ))}
                    </div>
                  </div>
                  {/* Sub-columns body */}
                  <div className="flex">
                    {weekVisiblePractitioners.map((p) => (
                      <div
                        key={`${di}-${p.id}`}
                        className="relative last:border-r-0"
                        style={{ flex: 1, minWidth: WEEK_PRACTITIONER_MIN_WIDTH, borderRight: '1px dashed #d1d5db' }}
                      >
                        {renderColumn(p.id, date, 0)}
                      </div>
                    ))}
                  </div>
                  {/* 休診日・営業時間外オーバーレイ */}
                  {renderScheduleOverlay(date, WEEK_HEADER_HEIGHT, slots.length * SLOT_HEIGHT)}
                </div>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
}
