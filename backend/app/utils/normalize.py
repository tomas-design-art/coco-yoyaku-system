"""検索キーワード正規化ユーティリティ.

ひらがな・カタカナ・半角カナ・全角英数の揺れを吸収し、
統一された文字列で比較できるようにする。
"""

import re
import unicodedata

# ひらがな → カタカナ 変換テーブル (U+3041‒U+3096 → U+30A1‒U+30F6)
_HIRA = "".join(chr(c) for c in range(0x3041, 0x3097))
_KATA = "".join(chr(c) for c in range(0x30A1, 0x30F7))
_H2K_TABLE = str.maketrans(_HIRA, _KATA)

# PostgreSQL translate() で使えるよう、文字列としても公開
HIRA_CHARS = _HIRA
KATA_CHARS = _KATA


def normalize_search_text(text: str | None) -> str:
    """検索テキストを正規化する。

    処理内容:
      1. NFKC 正規化 — 半角カナ→全角カナ、全角英数→半角英数
      2. ひらがな→カタカナ統一
      3. 全角スペース→半角スペース、連続スペース除去
      4. strip + lower (英字の大小吸収)

    >>> normalize_search_text("やまだ")
    'ヤマダ'
    >>> normalize_search_text("ﾔﾏﾀﾞ")
    'ヤマダ'
    >>> normalize_search_text("ヤマダ")
    'ヤマダ'
    >>> normalize_search_text("ＹＡＭＡＤＡ")
    'yamada'
    """
    if not text:
        return ""
    # NFKC: 半角カナ→全角カナ, 全角英数→半角英数
    text = unicodedata.normalize("NFKC", text)
    # ひらがな→カタカナ
    text = text.translate(_H2K_TABLE)
    # スペース正規化
    text = text.replace("\u3000", " ")
    text = re.sub(r"\s+", " ", text)
    return text.strip().lower()
