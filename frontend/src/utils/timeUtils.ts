/**
 * 5分刻み時間計算ユーティリティ
 */

export const SLOT_INTERVAL = 5;
export const DAY_START = 9 * 60;  // 09:00 (デフォルト)
export const DAY_END = 20 * 60;   // 20:00 (デフォルト)

export interface TimeSlot {
  minutes: number;
  label: string;
}

export function generateTimeSlots(dayStart = DAY_START, dayEnd = DAY_END): TimeSlot[] {
  const slots: TimeSlot[] = [];
  for (let m = dayStart; m < dayEnd; m += SLOT_INTERVAL) {
    const h = Math.floor(m / 60);
    const min = m % 60;
    slots.push({
      minutes: m,
      label: `${h}:${String(min).padStart(2, '0')}`,
    });
  }
  return slots;
}

export function minutesToTime(minutes: number): string {
  const h = Math.floor(minutes / 60);
  const m = minutes % 60;
  return `${String(h).padStart(2, '0')}:${String(m).padStart(2, '0')}`;
}

export function timeToMinutes(time: string): number {
  const [h, m] = time.split(':').map(Number);
  return h * 60 + m;
}

export function dateToMinutes(date: Date | string): number {
  const d = typeof date === 'string' ? new Date(date) : date;
  // UTC+9 (JST) で時・分を取得
  const jstMs = d.getTime() + 9 * 60 * 60 * 1000;
  const jst = new Date(jstMs);
  return jst.getUTCHours() * 60 + jst.getUTCMinutes();
}

export function slotIndex(minutes: number): number {
  return Math.floor((minutes - DAY_START) / SLOT_INTERVAL);
}

export function slotCount(startMinutes: number, endMinutes: number): number {
  return Math.floor((endMinutes - startMinutes) / SLOT_INTERVAL);
}

export function roundToSlot(minutes: number): number {
  return Math.round(minutes / SLOT_INTERVAL) * SLOT_INTERVAL;
}

export function formatDate(date: Date): string {
  const y = date.getFullYear();
  const m = String(date.getMonth() + 1).padStart(2, '0');
  const d = String(date.getDate()).padStart(2, '0');
  return `${y}-${m}-${d}`;
}

export function getWeekDates(baseDate: Date): Date[] {
  const day = baseDate.getDay();
  const monday = new Date(baseDate);
  monday.setDate(baseDate.getDate() - ((day + 6) % 7));

  const dates: Date[] = [];
  for (let i = 0; i < 7; i++) {
    const d = new Date(monday);
    d.setDate(monday.getDate() + i);
    dates.push(d);
  }
  return dates;
}

export const WEEKDAY_LABELS = ['日', '月', '火', '水', '木', '金', '土'];

/** JST の「今日」をローカルマシンの真夜と0時として返す */
export function getTodayJST(): Date {
  const now = Date.now();
  const jstMs = now + 9 * 60 * 60 * 1000;
  const jst = new Date(jstMs);
  return new Date(jst.getUTCFullYear(), jst.getUTCMonth(), jst.getUTCDate());
}

/** JST の現在時刻を分単位で返す */
export function getNowJSTMinutes(): number {
  const jstMs = Date.now() + 9 * 60 * 60 * 1000;
  const jst = new Date(jstMs);
  return jst.getUTCHours() * 60 + jst.getUTCMinutes();
}

export function generate5MinOptions(startHour = 9, endHour = 20): string[] {
  const options: string[] = [];
  for (let h = startHour; h <= endHour; h++) {
    for (let m = 0; m < 60; m += 5) {
      if (h === endHour && m > 0) break;
      options.push(`${String(h).padStart(2, '0')}:${String(m).padStart(2, '0')}`);
    }
  }
  return options;
}
