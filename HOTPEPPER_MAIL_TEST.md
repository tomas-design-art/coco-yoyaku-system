# HotPepperメール解析テスト仕様

**Date:** 2026-03-30
**Status:** 実装済み（4パターン対応）

---

## 1. 対応メールパターン一覧

| # | 件名パターン | event_type | 処理 |
|---|-------------|-----------|------|
| 0 | 予約連絡 | `created` | 全フィールド解析＋予約登録 |
| ① | 【明日】キャンセル連絡 | `cancelled` | 解析のみ（将来：既存予約キャンセル処理） |
| ② | 【当日○時○分】直前予約が入りました | `created` | 全フィールド解析＋予約登録 |
| ③ | 【明日】予約連絡 | `created` | 全フィールド解析＋予約登録 |
| ④ | 【SALON BOARD】本日分の未対応予約のお知らせ | `reminder` | 処理対象外（ValueError） |

---

## 2. パターン別の特徴

### パターン0: 通常予約（ベースライン）
- `[全員]` クーポンタグ
- ■合計金額セクションあり（6,700円）
- ■ご要望・ご相談あり（「-」= なし）
- 予約受付日時あり

### パターン①: キャンセル連絡
- 本文: 「ご予約のキャンセルがありました」
- **■合計金額セクションなし**（amount = None）
- **■ご要望・ご相談セクションなし**（note = None）
- クーポンにタグなし（[全員] 等がない → 1行目がクーポン名）
- クーポン金額に「→」（値引き表記: ６６００円→６０００円）

### パターン②: 直前予約
- 差出人名が「SALON BOARD直前予約お知らせ」
- `[新規]` クーポンタグ
- 構造はパターン0と同一

### パターン③: 翌日予約
- `[全員]` クーポンタグ
- BD から始まる予約番号（BE ではない）
- 2025年の日付（年をまたぐケース）

### パターン④: 未対応予約リマインダー
- **完全に異なる構造** — ■予約番号/■氏名/■来店日時セクションなし
- 「未対応予約のお知らせ」文言で判定
- 予約処理の対象外 → `ValueError` を送出

---

## 3. メール構造（SALON BOARD 予約通知）

```
■予約番号
　{value}
■氏名
　{value}
■来店日時
　{YYYY}年{MM}月{DD}日（{曜日}）{HH}:{MM}
■指名スタッフ
　{name | 指名なし}
■メニュー
　{menu_name}
　（所要時間目安：{N}時間）
■ご利用クーポン
　[{tag}]          ← ない場合あり（キャンセルメール等）
　{coupon_name}
　　{coupon_description}
■合計金額          ← ない場合あり（キャンセルメール等）
　予約時合計金額　{N,NNN}円
　...
■ご要望・ご相談    ← ない場合あり
　{text | -}

予約受付日時：{YYYY}年{MM}月{DD}日（{曜日}）{HH}:{MM}
```

値は全角スペース `　` でインデント。

---

## 4. 抽出フィールド

| フィールド | 型 | 必須 | 補足 |
|-----------|---|------|------|
| event_type | str | ○ | created / cancelled / changed / reminder |
| reservation_number | str | ○ | BE or BD プレフィックス |
| patient_name | str | ○ | ■氏名セクション |
| start_time | datetime (JST) | ○ | timezone-aware |
| end_time | datetime (JST) | ○ | start_time + duration |
| duration_minutes | int | — | デフォルト 60分 |
| practitioner_name | str? | — | 「指名なし」→ None |
| menu_name | str? | — | ■メニュー直下1行目 |
| amount | int? | — | 予約時合計金額（キャンセルでは None） |
| coupon_name | str? | — | タグの次行 or 1行目 |
| note | str? | — | 「-」→ None |
| received_at | datetime? | — | 予約受付日時 |

---

## 5. テスト実行

```bash
cd backend

# HotPepper メール解析テスト（4パターン + 異常系 + 補助系）
python -m pytest tests/test_hotpepper_parser.py -v

# 全テスト
python -m pytest tests/ -v
```

---

## 6. テストカバレッジ

| テストクラス | 対象 | テスト数 |
|-------------|------|---------|
| TestParseCreatedBase | パターン0: 通常予約 | 12 |
| TestParseCancelMail | パターン①: キャンセル | 11 |
| TestParseUrgentMail | パターン②: 直前予約 | 9 |
| TestParseNextDayMail | パターン③: 翌日予約 | 7 |
| TestParseReminderMail | パターン④: リマインダー | 2 |
| TestDetectEventType | 種別判定（実メール+合成） | 8 |
| TestParseErrors | 必須フィールド欠落 | 4 |
| TestParseDefaults | デフォルト値・指名あり | 2 |

---

## 7. 完了条件

- [x] 4パターンのサンプルメールでパースが成功
- [x] event_type が正しく判定される（created / cancelled / reminder）
- [x] キャンセルメールで amount = None（セクション欠如を正しく処理）
- [x] リマインダーメールで ValueError が発生
- [x] テスト（test_hotpepper_parser.py）が全パス
- [x] パース結果から予約がDBに正しく登録される（process_hotpepper_email）
- [x] 重複防止（source_ref で二重登録防止）
- [x] ログ出力（パース成功/失敗、患者新規/既存、予約作成/スキップ）

---

## 8. 今後の拡張

### 予約変更メール（event_type="changed"）
- `detect_event_type()` に「予約変更」パターンを追加済み
- `parse_hotpepper_mail()` は変更メールでも同じフィールドを返せる構造
- `process_hotpepper_email()` で `event_type == "changed"` 時に既存予約を更新するロジック追加が必要

### 予約キャンセルメール（event_type="cancelled"）
- パース済み（パターン①で検証完了）
- `process_hotpepper_email()` で `event_type == "cancelled"` 時に `source_ref` で検索 → ステータスを `CANCELLED` に変更するロジック追加が必要

### HotPepper 画面スクショ RPA
- Gemini 2.5 Flash のマルチモーダル（Vision）機能で画面キャプチャを解析
- 予約情報を OCR → 構造化データ変換 → 既存の予約登録パイプラインに接続
