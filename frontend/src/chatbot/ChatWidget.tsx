import React, { useState, useEffect, useRef, useCallback } from 'react';
import ChatBubble from './ChatBubble';
import ChatInput from './ChatInput';
import QuickReplyButtons from './QuickReplyButtons';
import { createSession, getSession, sendMessage, ChatAction } from './chatbotApi';

const SESSION_KEY = 'chatbot_session_id';

interface Message {
    role: 'user' | 'assistant';
    content: string;
}

const ChatWidget: React.FC = () => {
    const [open, setOpen] = useState(false);
    const [messages, setMessages] = useState<Message[]>([]);
    const [actions, setActions] = useState<ChatAction[]>([]);
    const [sessionId, setSessionId] = useState<string | null>(null);
    const [loading, setLoading] = useState(false);
    const [error, setError] = useState<string | null>(null);
    const messagesEndRef = useRef<HTMLDivElement>(null);

    const scrollToBottom = useCallback(() => {
        messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
    }, []);

    useEffect(() => {
        scrollToBottom();
    }, [messages, scrollToBottom]);

    // セッション復元 or 新規作成
    const initSession = useCallback(async () => {
        const storedId = localStorage.getItem(SESSION_KEY);
        if (storedId) {
            try {
                const sess = await getSession(storedId);
                if (sess.status === 'active') {
                    setSessionId(sess.session_id);
                    const restored: Message[] = sess.messages
                        .filter((m) => !('tool_call' in m))
                        .map((m) => ({ role: m.role as 'user' | 'assistant', content: m.content }));
                    setMessages(restored);
                    return;
                }
            } catch {
                // session expired or invalid — create new
            }
        }
        try {
            const sess = await createSession();
            setSessionId(sess.session_id);
            localStorage.setItem(SESSION_KEY, sess.session_id);
            const initial: Message[] = sess.messages.map((m) => ({
                role: m.role as 'user' | 'assistant',
                content: m.content,
            }));
            setMessages(initial);
        } catch {
            setError('チャットの初期化に失敗しました。');
        }
    }, []);

    useEffect(() => {
        if (open && !sessionId) {
            initSession();
        }
    }, [open, sessionId, initSession]);

    const handleSend = useCallback(
        async (text: string) => {
            if (!sessionId || loading) return;
            setMessages((prev) => [...prev, { role: 'user', content: text }]);
            setActions([]);
            setLoading(true);
            setError(null);

            try {
                const resp = await sendMessage(sessionId, text);
                setMessages((prev) => [...prev, { role: 'assistant', content: resp.response }]);
                setActions(resp.actions);

                if (resp.reservation_created) {
                    // 予約完了 — 新しいセッションを用意
                    localStorage.removeItem(SESSION_KEY);
                    setSessionId(null);
                }
            } catch {
                setError('送信に失敗しました。もう一度お試しください。');
            } finally {
                setLoading(false);
            }
        },
        [sessionId, loading],
    );

    const handleQuickReply = useCallback(
        (option: string) => {
            handleSend(option);
        },
        [handleSend],
    );

    const lastActions = actions.length > 0 ? actions[actions.length - 1] : null;

    return (
        <>
            {/* FAB */}
            {!open && (
                <button
                    className="cb-fab"
                    onClick={() => setOpen(true)}
                    aria-label="チャットを開く"
                >
                    💬
                </button>
            )}

            {/* Chat window */}
            {open && (
                <div className="cb-window">
                    <div className="cb-header">
                        <span className="cb-header-title">🏥 予約受付</span>
                        <button className="cb-close-btn" onClick={() => setOpen(false)} aria-label="閉じる">
                            ✕
                        </button>
                    </div>

                    <div className="cb-messages">
                        {messages.map((msg, i) => (
                            <ChatBubble key={i} role={msg.role} content={msg.content} />
                        ))}
                        {loading && (
                            <div className="cb-bubble-row cb-bubble-row--bot">
                                <div className="cb-bubble cb-bubble--bot cb-typing">入力中...</div>
                            </div>
                        )}
                        {error && <div className="cb-error">{error}</div>}
                        <div ref={messagesEndRef} />
                    </div>

                    {lastActions?.options && (
                        <QuickReplyButtons
                            options={lastActions.options}
                            onSelect={handleQuickReply}
                            disabled={loading}
                        />
                    )}

                    <ChatInput onSend={handleSend} disabled={loading} />
                </div>
            )}
        </>
    );
};

export default ChatWidget;
