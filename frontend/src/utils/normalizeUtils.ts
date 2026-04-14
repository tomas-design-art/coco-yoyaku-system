/**
 * 検索キーワード正規化ユーティリティ
 *
 * ひらがな⇔カタカナ・半角カナ→全角カナ・全角英数→半角英数の揺れを吸収し、
 * 統一された文字列で比較できるようにする。
 */

/**
 * ひらがな→カタカナ変換 (U+3041–U+3096 → U+30A1–U+30F6)
 */
function hiraToKata(ch: string): string {
    const cp = ch.charCodeAt(0);
    if (cp >= 0x3041 && cp <= 0x3096) {
        return String.fromCharCode(cp + 0x60);
    }
    return ch;
}

/**
 * 検索テキストを正規化する。
 *
 * 1. NFKC 正規化 — 半角カナ→全角カナ、全角英数→半角英数
 * 2. ひらがな→カタカナ統一
 * 3. 全角スペース→半角スペース、連続スペース除去
 * 4. trim + toLowerCase (英字の大小吸収)
 *
 * @example
 * normalizeSearchText("やまだ")   // "ヤマダ"
 * normalizeSearchText("ﾔﾏﾀﾞ")     // "ヤマダ"
 * normalizeSearchText("ヤマダ")   // "ヤマダ"
 * normalizeSearchText("ＹＡＭＡＤＡ") // "yamada"
 */
export function normalizeSearchText(text: string): string {
    if (!text) return '';
    // NFKC normalize: half-width kana → full-width, full-width ASCII → half-width
    let s = text.normalize('NFKC');
    // ひらがな → カタカナ
    s = Array.from(s).map(hiraToKata).join('');
    // スペース正規化
    s = s.replace(/\u3000/g, ' ').replace(/\s+/g, ' ');
    return s.trim().toLowerCase();
}
