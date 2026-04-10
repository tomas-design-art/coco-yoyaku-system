import { useState, useRef, useCallback } from 'react';
import type { TimeSlot } from '../../utils/timeUtils';
import { SLOT_INTERVAL } from '../../utils/timeUtils';

interface DragSelectProps {
  slots: TimeSlot[];
  slotHeight: number;
  onSlotClick: (minutes: number) => void;
  onDragSelect: (startMinutes: number, endMinutes: number) => void;
}

export default function DragSelect({ slots, slotHeight, onSlotClick, onDragSelect }: DragSelectProps) {
  const [isDragging, setIsDragging] = useState(false);
  const [dragStart, setDragStart] = useState<number | null>(null);
  const [dragEnd, setDragEnd] = useState<number | null>(null);
  const containerRef = useRef<HTMLDivElement>(null);

  const getSlotFromY = useCallback(
    (y: number): number => {
      const index = Math.floor(y / slotHeight);
      const clampedIndex = Math.max(0, Math.min(index, slots.length - 1));
      return slots[clampedIndex].minutes;
    },
    [slots, slotHeight]
  );

  const handleMouseDown = useCallback(
    (e: React.MouseEvent) => {
      if (e.button !== 0) return;
      const rect = containerRef.current?.getBoundingClientRect();
      if (!rect) return;
      const y = e.clientY - rect.top;
      const minutes = getSlotFromY(y);
      setIsDragging(true);
      setDragStart(minutes);
      setDragEnd(minutes);
    },
    [getSlotFromY]
  );

  const handleMouseMove = useCallback(
    (e: React.MouseEvent) => {
      if (!isDragging) return;
      const rect = containerRef.current?.getBoundingClientRect();
      if (!rect) return;
      const y = e.clientY - rect.top;
      setDragEnd(getSlotFromY(y));
    },
    [isDragging, getSlotFromY]
  );

  const handleMouseUp = useCallback(() => {
    if (!isDragging || dragStart === null || dragEnd === null) return;
    setIsDragging(false);

    const start = Math.min(dragStart, dragEnd);
    const end = Math.max(dragStart, dragEnd) + SLOT_INTERVAL;

    if (start === end - SLOT_INTERVAL) {
      onSlotClick(start);
    } else {
      onDragSelect(start, end);
    }

    setDragStart(null);
    setDragEnd(null);
  }, [isDragging, dragStart, dragEnd, onSlotClick, onDragSelect]);

  const selectionStart = dragStart !== null && dragEnd !== null ? Math.min(dragStart, dragEnd) : null;
  const selectionEnd = dragStart !== null && dragEnd !== null ? Math.max(dragStart, dragEnd) + SLOT_INTERVAL : null;

  return (
    <div
      ref={containerRef}
      className="relative select-none"
      style={{ cursor: isDragging ? 'col-resize' : 'pointer' }}
      onMouseDown={handleMouseDown}
      onMouseMove={handleMouseMove}
      onMouseUp={handleMouseUp}
      onMouseLeave={handleMouseUp}
    >
      {slots.map((slot) => {
        const nextMin = slot.minutes + SLOT_INTERVAL;
        let borderStyle: string;
        if (nextMin % 60 === 0) {
          borderStyle = '2px solid #6b7280'; // 毎時 — 太灰線
        } else if (nextMin % 30 === 0) {
          borderStyle = '1.5px solid #b0b7c0'; // 30分 — 中灰線
        } else if (nextMin % 15 === 0) {
          borderStyle = '1px solid #d1d5db'; // 15分 — 薄灰実線
        } else {
          borderStyle = '0.5px solid #e5e7eb'; // 5分 — 極薄灰線
        }
        return (
          <div
            key={slot.minutes}
            style={{ height: slotHeight, borderBottom: borderStyle }}
            className="hover:bg-blue-50"
          />
        );
      })}

      {/* Selection highlight */}
      {selectionStart !== null && selectionEnd !== null && (
        <div
          className="absolute left-0 right-0 bg-blue-200 opacity-50 pointer-events-none"
          style={{
            top: ((selectionStart - slots[0].minutes) / SLOT_INTERVAL) * slotHeight,
            height: ((selectionEnd - selectionStart) / SLOT_INTERVAL) * slotHeight,
          }}
        />
      )}
    </div>
  );
}
