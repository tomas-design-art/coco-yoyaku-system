import React from 'react';

interface Props {
    role: 'user' | 'assistant';
    content: string;
}

const ChatBubble: React.FC<Props> = ({ role, content }) => {
    const isUser = role === 'user';

    return (
        <div className={`cb-bubble-row ${isUser ? 'cb-bubble-row--user' : 'cb-bubble-row--bot'}`}>
            <div className={`cb-bubble ${isUser ? 'cb-bubble--user' : 'cb-bubble--bot'}`}>
                {content.split('\n').map((line, i) => (
                    <React.Fragment key={i}>
                        {line}
                        {i < content.split('\n').length - 1 && <br />}
                    </React.Fragment>
                ))}
            </div>
        </div>
    );
};

export default ChatBubble;
