import { useState, useEffect } from 'react';
import { X, Check } from 'lucide-react';
import type { Notification } from '../../types';
import { getNotifications, markNotificationRead } from '../../api/client';

interface NotificationPanelProps {
  onClose: () => void;
}

export default function NotificationPanel({ onClose }: NotificationPanelProps) {
  const [notifications, setNotifications] = useState<Notification[]>([]);

  useEffect(() => {
    getNotifications().then((res) => setNotifications(res.data));
  }, []);

  const handleMarkRead = async (id: number) => {
    await markNotificationRead(id);
    setNotifications((prev) =>
      prev.map((n) => (n.id === id ? { ...n, is_read: true } : n))
    );
  };

  const EVENT_LABELS: Record<string, string> = {
    new_reservation: '新規予約',
    conflict_detected: '競合検出',
    cancel_requested: 'キャンセル申請',
    change_requested: '変更申請',
    reservation_confirmed: '予約確定',
    cancel_approved: 'キャンセル承認',
    change_approved: '変更承認',
    hold_expired: 'HOLD期限切れ',
    hotpepper_import: 'HP取込',
    line_proposal: 'LINE予約提案',
    hotpepper_cancel_remind: 'HPキャンセルリマインド',
    hotpepper_sync_reminder: 'HP押さえリマインド',
    hotpepper_hold_reminder: 'HP押さえリマインド',
  };

  return (
    <div className="fixed right-0 top-0 h-full w-80 bg-white shadow-xl z-40 flex flex-col">
      <div className="flex items-center justify-between p-4 border-b">
        <h3 className="font-semibold">通知一覧</h3>
        <button onClick={onClose} className="p-1 hover:bg-gray-100 rounded"><X size={18} /></button>
      </div>
      <div className="flex-1 overflow-auto">
        {notifications.length === 0 && (
          <p className="p-4 text-center text-gray-500 text-sm">通知はありません</p>
        )}
        {notifications.map((n) => (
          <div
            key={n.id}
            className={`px-4 py-3 border-b text-sm ${n.is_read ? 'bg-white' : 'bg-blue-50'}`}
          >
            <div className="flex items-center justify-between mb-1">
              <span className="text-xs font-medium text-gray-500">
                {EVENT_LABELS[n.event_type] || n.event_type}
              </span>
              {!n.is_read && (
                <button
                  onClick={() => handleMarkRead(n.id)}
                  className="text-blue-500 hover:text-blue-700"
                  title="既読にする"
                >
                  <Check size={14} />
                </button>
              )}
            </div>
            <p className="text-gray-700">{n.message}</p>
            <p className="text-xs text-gray-400 mt-1">
              {new Date(n.created_at).toLocaleString('ja-JP')}
            </p>
          </div>
        ))}
      </div>
    </div>
  );
}
