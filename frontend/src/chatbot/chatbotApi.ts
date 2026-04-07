/**
 * チャットボット APIクライアント
 * 管理画面のclient.tsとは独立。ウィジェット単体でも動作可能。
 */

declare global {
    interface Window {
        __clinicChatbotApiBase?: string;
    }
}

function resolveApiBase(): string {
    const explicit = window.__clinicChatbotApiBase;
    if (explicit && explicit.trim()) return explicit.trim().replace(/\/$/, '');
    return '/api/web_chatbot';
}

const API_BASE = resolveApiBase();

export interface ChatAction {
    type: string;
    options?: string[];
}

export interface ChatReservation {
    id: number;
    date: string;
    start_time: string;
    end_time: string;
    menu: string;
    patient_name: string;
}

export interface ChatMessageResponse {
    session_id: string;
    response: string;
    actions: ChatAction[];
    reservation_created: ChatReservation | null;
}

export interface SessionResponse {
    session_id: string;
    messages: Array<{ role: string; content: string }>;
    status: string;
}

export async function createSession(): Promise<SessionResponse> {
    const res = await fetch(`${API_BASE}/session`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({}),
    });
    if (!res.ok) throw new Error('セッション作成に失敗しました');
    return res.json();
}

export async function getSession(sessionId: string): Promise<SessionResponse> {
    const res = await fetch(`${API_BASE}/session/${encodeURIComponent(sessionId)}`);
    if (!res.ok) throw new Error('セッション取得に失敗しました');
    return res.json();
}

export async function sendMessage(
    sessionId: string,
    message: string,
): Promise<ChatMessageResponse> {
    const res = await fetch(`${API_BASE}/message`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ session_id: sessionId, message }),
    });
    if (!res.ok) throw new Error('メッセージ送信に失敗しました');
    return res.json();
}
