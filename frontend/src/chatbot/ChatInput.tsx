import React, { useState, useRef, KeyboardEvent } from 'react';

interface Props {
    onSend: (message: string) => void;
    disabled?: boolean;
}

const ChatInput: React.FC<Props> = ({ onSend, disabled }) => {
    const [text, setText] = useState('');
    const inputRef = useRef<HTMLInputElement>(null);

    const handleSend = () => {
        const trimmed = text.trim();
        if (!trimmed || disabled) return;
        onSend(trimmed);
        setText('');
        inputRef.current?.focus();
    };

    const handleKeyDown = (e: KeyboardEvent) => {
        if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault();
            handleSend();
        }
    };

    return (
        <div className="cb-input-area">
            <input
                ref={inputRef}
                className="cb-input"
                type="text"
                placeholder="メッセージを入力..."
                value={text}
                onChange={(e) => setText(e.target.value)}
                onKeyDown={handleKeyDown}
                disabled={disabled}
                maxLength={2000}
            />
            <button
                className="cb-send-btn"
                onClick={handleSend}
                disabled={disabled || !text.trim()}
                aria-label="送信"
            >
                ▶
            </button>
        </div>
    );
};

export default ChatInput;
