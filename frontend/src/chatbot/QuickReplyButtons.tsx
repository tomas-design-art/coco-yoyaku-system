import React from 'react';

interface Props {
    options: string[];
    onSelect: (option: string) => void;
    disabled?: boolean;
}

const QuickReplyButtons: React.FC<Props> = ({ options, onSelect, disabled }) => {
    if (!options.length) return null;

    return (
        <div className="cb-quick-replies">
            {options.map((opt, i) => (
                <button
                    key={i}
                    className="cb-quick-btn"
                    onClick={() => onSelect(opt)}
                    disabled={disabled}
                >
                    {opt}
                </button>
            ))}
        </div>
    );
};

export default QuickReplyButtons;
