import { useState, useCallback, useEffect, useMemo } from 'react';
import { BrowserRouter, Routes, Route, Link, useLocation, useNavigate } from 'react-router-dom';
import { Calendar, Users, Settings, Stethoscope, Menu as MenuIcon, Volume2, VolumeX, Palette, Bot, CalendarDays, CheckCircle, Lock, Unlock, LogOut, X } from 'lucide-react';
import TimeTable from './components/TimeTable/TimeTable';
import ReservationForm from './components/ReservationForm/ReservationForm';
import ReservationDetail from './components/ReservationDetail';
import PractitionerManager from './components/Settings/PractitionerManager';
import MenuManager from './components/Settings/MenuManager';
import ColorManager from './components/Settings/ColorManager';
import ChatbotSettings from './components/Settings/ChatbotSettings';
import WeeklyScheduleManager from './components/Settings/WeeklyScheduleManager';
import PractitionerScheduleManager from './components/Settings/PractitionerScheduleManager';
import SystemSettings from './components/Settings/SystemSettings';
import PatientList from './components/PatientList';
import NotificationBell from './components/Notification/NotificationBell';
import AlertPopup from './components/Notification/AlertPopup';
import NotificationPanel from './components/Notification/NotificationPanel';
import SeriesExtensionModal from './components/Notification/SeriesExtensionModal';
import HotPepperSync from './components/HotPepperSync';
import PublicReserve from './components/PublicReserve';
import AdminLoginModal from './components/Auth/AdminLoginModal';
import { AuthProvider, useAuth } from './hooks/useAuth';
import { useSSE } from './hooks/useSSE';
import { useNotification } from './hooks/useNotification';
import { rescheduleReservation, getSeries, getPendingSeriesAlerts } from './api/client';
import { extractErrorMessage } from './utils/errorUtils';
import type { Reservation, SeriesResponse } from './types';

type PendingRescheduleTarget = {
  practitionerId: number;
  startMinutes: number;
  date: Date;
};

function NavLink({ to, children, locked }: { to: string; children: React.ReactNode; locked?: boolean }) {
  const location = useLocation();
  const active = location.pathname === to || (to !== '/' && location.pathname.startsWith(to));
  return (
    <Link to={to} className={`px-3 py-2 rounded text-sm font-medium flex items-center gap-1 ${active ? 'bg-blue-100 text-blue-700' : 'text-gray-600 hover:bg-gray-100'}`}>
      {children}
      {locked && <Lock size={12} className="text-gray-400" />}
    </Link>
  );
}

function AppContent() {
  const { role, adminLogout, logout } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const isAdmin = role === 'admin';

  const [showReservationForm, setShowReservationForm] = useState(false);
  const [showNotificationPanel, setShowNotificationPanel] = useState(false);
  const [selectedReservation, setSelectedReservation] = useState<Reservation | null>(null);
  const [refreshKey, setRefreshKey] = useState(0);
  const [formInitialData, setFormInitialData] = useState<{
    practitionerId?: number;
    date?: Date;
    startMinutes?: number;
    endMinutes?: number;
    isSingleClick?: boolean;
  }>({});

  // Admin login modal state
  const [showAdminLogin, setShowAdminLogin] = useState(false);
  const [adminLoginTarget, setAdminLoginTarget] = useState<string | null>(null);

  // Reschedule mode state
  const [reschedulingReservation, setReschedulingReservation] = useState<Reservation | null>(null);
  const [pendingRescheduleTarget, setPendingRescheduleTarget] = useState<PendingRescheduleTarget | null>(null);
  const [isSubmittingReschedule, setIsSubmittingReschedule] = useState(false);
  const [rescheduleSuccess, setRescheduleSuccess] = useState<string | null>(null);
  const [rescheduleError, setRescheduleError] = useState<string | null>(null);
  const [rescheduleDurationOffset, setRescheduleDurationOffset] = useState(0);

  // Series extension modal state
  const [seriesExtensionTarget, setSeriesExtensionTarget] = useState<SeriesResponse | null>(null);
  const [isTimeTableFullscreen, setIsTimeTableFullscreen] = useState(false);

  const { toasts, unreadCount, audioInitialized, enableAudio, addToast, removeToast, clearUnread } = useNotification();

  const handleSSEEvent = useCallback((event: { event_type: string; data: Record<string, unknown> }) => {
    const msg = (event.data.message as string) || event.event_type;
    if (event.event_type === 'series_expiring') {
      // シリーズ延長通知 — モーダルを表示
      const seriesId = event.data.series_id as number | undefined;
      if (seriesId) {
        getSeries(seriesId).then((res) => {
          setSeriesExtensionTarget(res.data);
        }).catch(() => {
          addToast(msg, 'warning');
        });
      } else {
        addToast(msg, 'warning');
      }
    } else if (event.event_type === 'conflict_detected') {
      addToast(msg, 'error');
    } else if (event.event_type === 'hold_expired') {
      addToast(msg, 'warning');
    } else if (event.event_type === 'hotpepper_sync_reminder') {
      addToast(msg, 'warning');
    } else {
      addToast(msg, 'info');
    }
    setRefreshKey((k) => k + 1);
  }, [addToast]);

  useSSE(handleSSEEvent);

  // 画面起動時: SSE で受け取れなかった未対応のシリーズ延長アラートをキャッチアップ
  useEffect(() => {
    getPendingSeriesAlerts()
      .then((res) => {
        const alerts = res.data ?? [];
        if (alerts.length > 0) {
          setSeriesExtensionTarget(alerts[0]); // 最新1件をモーダル表示
        }
      })
      .catch(() => { /* ignore */ });
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  const refresh = () => setRefreshKey((k) => k + 1);

  const handleSlotClick = (practitionerId: number, startMinutes: number, date: Date) => {
    setFormInitialData({ practitionerId, date, startMinutes, endMinutes: startMinutes + 30, isSingleClick: true });
    setShowReservationForm(true);
  };

  const handleDragSelect = (practitionerId: number, startMinutes: number, endMinutes: number, date: Date) => {
    setFormInitialData({ practitionerId, date, startMinutes, endMinutes, isSingleClick: false });
    setShowReservationForm(true);
  };

  // Start reschedule mode from ReservationDetail
  const handleStartReschedule = (reservation: Reservation) => {
    const currentStart = new Date(reservation.start_time);
    setSelectedReservation(null); // close detail
    setReschedulingReservation(reservation);
    setPendingRescheduleTarget({
      practitionerId: reservation.practitioner_id,
      startMinutes: currentStart.getHours() * 60 + currentStart.getMinutes(),
      date: currentStart,
    });
    setRescheduleError(null);
    setRescheduleDurationOffset(0);
  };

  // Handle slot click while in reschedule mode
  const handleRescheduleSlotClick = (practitionerId: number, startMinutes: number, date: Date) => {
    if (!reschedulingReservation) return;
    setRescheduleError(null);
    setPendingRescheduleTarget({
      practitionerId,
      startMinutes,
      date,
    });
  };

  const pendingRescheduleLabel = useMemo(() => {
    if (!pendingRescheduleTarget || !reschedulingReservation) return null;
    const baseDurationMin = (new Date(reschedulingReservation.end_time).getTime() - new Date(reschedulingReservation.start_time).getTime()) / 60000;
    const durationMin = baseDurationMin + rescheduleDurationOffset;

    const startH = Math.floor(pendingRescheduleTarget.startMinutes / 60);
    const startM = pendingRescheduleTarget.startMinutes % 60;
    const endMinutes = pendingRescheduleTarget.startMinutes + durationMin;
    const endH = Math.floor(endMinutes / 60);
    const endM = endMinutes % 60;
    const date = pendingRescheduleTarget.date;
    const displayDate = `${date.getMonth() + 1}/${date.getDate()}`;
    const startTimeStr = `${String(startH).padStart(2, '0')}:${String(startM).padStart(2, '0')}`;
    const endTimeStr = `${String(endH).padStart(2, '0')}:${String(endM).padStart(2, '0')}`;
    const offsetLabel = rescheduleDurationOffset !== 0
      ? `（時間${rescheduleDurationOffset > 0 ? '+' : ''}${rescheduleDurationOffset}分）`
      : '';
    return `${displayDate} ${startTimeStr}〜${endTimeStr}${offsetLabel}`;
  }, [pendingRescheduleTarget, reschedulingReservation, rescheduleDurationOffset]);

  const confirmPendingReschedule = useCallback(async () => {
    if (!reschedulingReservation || !pendingRescheduleTarget || isSubmittingReschedule) return;

    const r = reschedulingReservation;
    const baseDurationMin = (new Date(r.end_time).getTime() - new Date(r.start_time).getTime()) / 60000;
    const durationMin = baseDurationMin + rescheduleDurationOffset;

    const startH = Math.floor(pendingRescheduleTarget.startMinutes / 60);
    const startM = pendingRescheduleTarget.startMinutes % 60;
    const endMinutes = pendingRescheduleTarget.startMinutes + durationMin;
    const endH = Math.floor(endMinutes / 60);
    const endM = endMinutes % 60;
    const date = pendingRescheduleTarget.date;
    const dateStr = `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}-${String(date.getDate()).padStart(2, '0')}`;
    const startTimeStr = `${String(startH).padStart(2, '0')}:${String(startM).padStart(2, '0')}`;
    const endTimeStr = `${String(endH).padStart(2, '0')}:${String(endM).padStart(2, '0')}`;

    setRescheduleError(null);
    setIsSubmittingReschedule(true);
    try {
      await rescheduleReservation(r.id, {
        new_start_time: `${dateStr}T${startTimeStr}:00+09:00`,
        new_end_time: `${dateStr}T${endTimeStr}:00+09:00`,
        new_practitioner_id: pendingRescheduleTarget.practitionerId !== r.practitioner_id ? pendingRescheduleTarget.practitionerId : undefined,
      });
      setReschedulingReservation(null);
      setPendingRescheduleTarget(null);
      setRescheduleDurationOffset(0);
      setRescheduleSuccess('予約を変更しました');
      refresh();
      setTimeout(() => setRescheduleSuccess(null), 2000);
    } catch (err: unknown) {
      setRescheduleError(extractErrorMessage(err, '予約変更に失敗しました'));
    } finally {
      setIsSubmittingReschedule(false);
    }
  }, [reschedulingReservation, pendingRescheduleTarget, isSubmittingReschedule, rescheduleDurationOffset]);

  const cancelReschedule = () => {
    setReschedulingReservation(null);
    setPendingRescheduleTarget(null);
    setRescheduleError(null);
    setIsSubmittingReschedule(false);
    setRescheduleDurationOffset(0);
  };

  useEffect(() => {
    if (location.pathname !== '/' && isTimeTableFullscreen) {
      setIsTimeTableFullscreen(false);
    }
  }, [location.pathname, isTimeTableFullscreen]);

  const showAppHeader = !(location.pathname === '/' && isTimeTableFullscreen);

  return (
    <div className="flex flex-col h-screen">
      {/* Header */}
      {showAppHeader && (
        <header className="bg-white shadow-sm border-b z-20">
          <div className="flex items-center justify-between px-4 py-2">
            <div className="flex items-center gap-4">
              <h1 className="text-lg font-bold text-gray-900">🦴 予約管理</h1>
              <nav className="flex items-center gap-1">
                <NavLink to="/"><Calendar size={16} className="inline mr-1" />タイムテーブル</NavLink>
                <NavLink to="/patients"><Users size={16} className="inline mr-1" />患者</NavLink>
                <AdminNavLink to="/settings/practitioners" isAdmin={isAdmin} onRequireAdmin={setAdminLoginTarget}>
                  <Stethoscope size={16} className="inline mr-1" />施術者
                </AdminNavLink>
                <AdminNavLink to="/settings/menus" isAdmin={isAdmin} onRequireAdmin={setAdminLoginTarget}>
                  <MenuIcon size={16} className="inline mr-1" />メニュー
                </AdminNavLink>
                <AdminNavLink to="/settings/colors" isAdmin={isAdmin} onRequireAdmin={setAdminLoginTarget}>
                  <Palette size={16} className="inline mr-1" />色設定
                </AdminNavLink>
                <AdminNavLink to="/settings/chatbot" isAdmin={isAdmin} onRequireAdmin={setAdminLoginTarget}>
                  <Bot size={16} className="inline mr-1" />チャットボット
                </AdminNavLink>
                <AdminNavLink to="/settings/schedule" isAdmin={isAdmin} onRequireAdmin={setAdminLoginTarget}>
                  <CalendarDays size={16} className="inline mr-1" />院営業スケジュール
                </AdminNavLink>
                <NavLink to="/settings/practitioner-schedules"><CalendarDays size={16} className="inline mr-1" />職員勤務スケジュール</NavLink>
                <AdminNavLink to="/settings" isAdmin={isAdmin} onRequireAdmin={setAdminLoginTarget}>
                  <Settings size={16} className="inline mr-1" />設定
                </AdminNavLink>
                <NavLink to="/hotpepper">🔥 HP同期</NavLink>
              </nav>
            </div>
            <div className="flex items-center gap-2">
              {isAdmin && (
                <div className="flex items-center gap-1 text-sm text-green-700 bg-green-50 px-2 py-1 rounded">
                  <Unlock size={14} />
                  <span>管理者</span>
                  <button
                    onClick={adminLogout}
                    className="ml-1 text-xs text-green-600 hover:text-green-800 underline"
                  >
                    戻る
                  </button>
                </div>
              )}
              <button
                onClick={enableAudio}
                className={`p-2 rounded-full ${audioInitialized ? 'text-green-500' : 'text-gray-400 hover:text-gray-600'}`}
                title={audioInitialized ? '通知音ON' : 'クリックして通知音を有効化'}
              >
                {audioInitialized ? <Volume2 size={18} /> : <VolumeX size={18} />}
              </button>
              <NotificationBell
                unreadCount={unreadCount}
                onClick={() => { setShowNotificationPanel(!showNotificationPanel); clearUnread(); }}
              />
              <button
                onClick={() => { logout(); }}
                className="p-2 rounded-full text-gray-400 hover:text-red-500"
                title="ログアウト"
              >
                <LogOut size={18} />
              </button>
            </div>
          </div>
        </header>
      )}

      {/* Main */}
      <main className="flex-1 overflow-auto bg-gray-50">
        <Routes>
          <Route path="/" element={
            <TimeTable
              onSlotClick={handleSlotClick}
              onDragSelect={handleDragSelect}
              onReservationClick={setSelectedReservation}
              refreshKey={refreshKey}
              reschedulingReservation={reschedulingReservation}
              onRescheduleSlotClick={handleRescheduleSlotClick}
              onCancelReschedule={cancelReschedule}
              pendingRescheduleTarget={pendingRescheduleTarget}
              pendingRescheduleLabel={pendingRescheduleLabel}
              onConfirmReschedule={confirmPendingReschedule}
              canConfirmReschedule={!!pendingRescheduleTarget && !isSubmittingReschedule}
              isConfirmingReschedule={isSubmittingReschedule}
              rescheduleDurationOffset={rescheduleDurationOffset}
              onRescheduleDurationChange={(delta) => setRescheduleDurationOffset(prev => prev + delta)}
              isFullscreenMode={isTimeTableFullscreen}
              onToggleFullscreen={() => setIsTimeTableFullscreen((prev) => !prev)}
              fullscreenRightControls={isTimeTableFullscreen ? (
                <>
                  <NotificationBell
                    unreadCount={unreadCount}
                    onClick={() => { setShowNotificationPanel(!showNotificationPanel); clearUnread(); }}
                  />
                  <button
                    onClick={() => setIsTimeTableFullscreen(false)}
                    className="p-1.5 text-gray-500 hover:text-gray-700 hover:bg-gray-100 rounded"
                    title="全画面表示を終了"
                  >
                    <X size={16} />
                  </button>
                </>
              ) : null}
            />
          } />
          <Route path="/patients" element={<PatientList />} />
          <Route path="/settings/practitioners" element={<PractitionerManager />} />
          <Route path="/settings/menus" element={<MenuManager />} />
          <Route path="/settings/colors" element={<ColorManager />} />
          <Route path="/settings/chatbot" element={<ChatbotSettings />} />
          <Route path="/settings/schedule" element={<WeeklyScheduleManager />} />
          <Route path="/settings/practitioner-schedules" element={<PractitionerScheduleManager />} />
          <Route path="/settings" element={<SystemSettings />} />
          <Route path="/hotpepper" element={<HotPepperSync />} />
          <Route path="/reserve" element={<PublicReserve />} />
        </Routes>
      </main>

      {/* Modals */}
      <ReservationForm
        isOpen={showReservationForm}
        onClose={() => setShowReservationForm(false)}
        onSuccess={refresh}
        initialData={formInitialData}
      />

      {selectedReservation && (
        <ReservationDetail
          reservation={selectedReservation}
          onClose={() => setSelectedReservation(null)}
          onUpdate={refresh}
          onStartReschedule={handleStartReschedule}
        />
      )}

      {showNotificationPanel && (
        <NotificationPanel onClose={() => setShowNotificationPanel(false)} />
      )}

      {/* Reschedule error */}
      {rescheduleError && (
        <div className="fixed top-4 left-1/2 -translate-x-1/2 z-[70] bg-red-500 text-white px-6 py-3 rounded-lg shadow-2xl flex items-center gap-2 cursor-pointer"
          onClick={() => setRescheduleError(null)}
        >
          <span className="font-medium">{rescheduleError}</span>
        </div>
      )}

      {/* Reschedule success popup */}
      {rescheduleSuccess && (
        <div className="fixed inset-0 flex items-center justify-center z-[70] pointer-events-none">
          <div className="bg-green-500 text-white px-6 py-3 rounded-lg shadow-2xl flex items-center gap-2 animate-bounce">
            <CheckCircle size={20} />
            <span className="font-medium">{rescheduleSuccess}</span>
          </div>
        </div>
      )}

      {/* Toast notifications */}
      <AlertPopup toasts={toasts} onDismiss={removeToast} />

      {/* Series extension modal */}
      {seriesExtensionTarget && (
        <SeriesExtensionModal
          series={seriesExtensionTarget}
          onClose={() => setSeriesExtensionTarget(null)}
          onAction={refresh}
        />
      )}

      {/* Admin login modal */}
      <AdminLoginModal
        isOpen={showAdminLogin || adminLoginTarget !== null}
        onClose={() => { setShowAdminLogin(false); setAdminLoginTarget(null); }}
        onSuccess={() => {
          setShowAdminLogin(false);
          if (adminLoginTarget) {
            navigate(adminLoginTarget);
          }
          setAdminLoginTarget(null);
        }}
      />
    </div>
  );
}

function AdminNavLink({ to, isAdmin, onRequireAdmin, children }: {
  to: string;
  isAdmin: boolean;
  onRequireAdmin: (path: string) => void;
  children: React.ReactNode;
}) {
  const location = useLocation();
  const active = location.pathname === to || (to !== '/' && location.pathname.startsWith(to));

  const handleClick = (e: React.MouseEvent) => {
    if (!isAdmin) {
      e.preventDefault();
      onRequireAdmin(to);
    }
  };

  return (
    <Link
      to={isAdmin ? to : '#'}
      onClick={handleClick}
      className={`px-3 py-2 rounded text-sm font-medium flex items-center gap-1 ${active ? 'bg-blue-100 text-blue-700' : 'text-gray-600 hover:bg-gray-100'}`}
    >
      {children}
      {!isAdmin && <Lock size={12} className="text-gray-400" />}
    </Link>
  );
}

function App() {
  return (
    <BrowserRouter>
      <AuthProvider>
        <AuthGate />
      </AuthProvider>
    </BrowserRouter>
  );
}

function AuthGate() {
  const location = useLocation();
  if (location.pathname.startsWith('/reserve')) return <PublicReserve />;
  // PIN認証を無効化: 常にメイン画面を表示
  return <AppContent />;
}

export default App
