# 職員勤務スケジュール管理（PATCH_006）

**Date:** 2026-03-22
**目的:** 施術者の出勤/休みスケジュールを管理し、休みの日に予約が入らないようにする。突発休み時に既存予約の振替候補を提示する。

---

## Step A: 職員勤務スケジュール基盤

### 1. DB設計

#### 新テーブル: practitioner_schedules（デフォルト出勤パターン）

```sql
CREATE TABLE practitioner_schedules (
    id SERIAL PRIMARY KEY,
    practitioner_id INTEGER NOT NULL REFERENCES practitioners(id),
    day_of_week INTEGER NOT NULL,          -- 0=日, 1=月, 2=火, ..., 6=土
    start_time TIME NOT NULL,              -- 出勤開始（例: 10:00）
    end_time TIME NOT NULL,                -- 出勤終了（例: 20:00）
    is_working BOOLEAN DEFAULT TRUE,       -- true=出勤日, false=定休日
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(practitioner_id, day_of_week)   -- 施術者×曜日で一意
);
```

#### 新テーブル: schedule_overrides（特定日の上書き）

```sql
CREATE TABLE schedule_overrides (
    id SERIAL PRIMARY KEY,
    practitioner_id INTEGER NOT NULL REFERENCES practitioners(id),
    date DATE NOT NULL,                    -- 対象日
    is_working BOOLEAN NOT NULL,           -- true=臨時出勤, false=臨時休み
    start_time TIME,                       -- 臨時出勤の場合の開始時間（NULLならデフォルト）
    end_time TIME,                         -- 臨時出勤の場合の終了時間（NULLならデフォルト）
    reason VARCHAR(200),                   -- 理由（例:「体調不良」「研修」「振替出勤」）
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(practitioner_id, date)          -- 施術者×日付で一意
);
```

### 2. スケジュール判定ロジック

```python
async def is_practitioner_available(
    db: AsyncSession,
    practitioner_id: int,
    target_date: date,
    start_time: time,
    end_time: time
) -> tuple[bool, str]:
    """
    施術者が指定日時に勤務しているか判定する。
    
    Returns:
        (True, "") → 勤務中、予約可能
        (False, "定休日です") → 定休日
        (False, "臨時休みです（体調不良）") → 臨時休み
        (False, "勤務時間外です（09:00-18:00）") → 時間外
    
    判定順序:
    1. schedule_overrides にその日のレコードがあるか？
       → あり & is_working=false → 休み
       → あり & is_working=true → 出勤（時間チェック）
    2. なければ practitioner_schedules のデフォルトパターンを見る
       → is_working=false → 定休日
       → is_working=true → 出勤（時間チェック）
    3. どちらにもレコードがない → デフォルト出勤扱い（営業時間で判定）
    """
```

### 3. 予約登録時のバリデーション追加

予約登録API（`POST /api/reservations`）に以下のチェックを追加:

```python
# 予約登録前にスケジュールチェック
available, reason = await is_practitioner_available(
    db, data.practitioner_id, data.start_time.date(),
    data.start_time.time(), data.end_time.time()
)
if not available:
    raise HTTPException(
        status_code=400,
        detail=f"この施術者は予約できません: {reason}"
    )
```

### 4. タイムテーブルUIの休み表示

休みの施術者×日のセルをグレーアウトして、クリック/ドラッグを無効化する。

```typescript
// TimeTable.tsx
// 各施術者×日のスロットで、スケジュールAPIから休み情報を取得
// 休みの場合:
//   - 背景をグレー（#F3F4F6）の斜線パターン
//   - クリック/ドラッグを無効化
//   - ホバー時にツールチップ「定休日」「臨時休み（体調不良）」
```

### 5. API

| Method | Path | 説明 | 権限 |
|--------|------|------|------|
| GET | /api/practitioners/{id}/schedule | デフォルト出勤パターン取得 | スタッフ |
| PUT | /api/practitioners/{id}/schedule | デフォルト出勤パターン更新 | 管理者 |
| GET | /api/schedule-overrides?practitioner_id=&start_date=&end_date= | 期間内の上書き一覧 | スタッフ |
| POST | /api/schedule-overrides | 臨時休み/臨時出勤を登録 | 管理者 |
| DELETE | /api/schedule-overrides/{id} | 上書きを削除 | 管理者 |
| GET | /api/practitioners/availability?date=&start_time=&end_time= | 指定日時の全施術者の勤務状況 | スタッフ |

### 6. 管理画面: 職員勤務スケジュール設定（/settings/practitioner-schedules）

```
┌──────────────────────────────────────────────────┐
│  職員勤務スケジュール設定              スタッフ共通  │
├──────────────────────────────────────────────────┤
│                                                  │
│  施術者: [院長 ▼]                                │
│                                                  │
│  ┌─────┬────────┬────────┬──────┐               │
│  │ 曜日 │ 出勤   │ 開始   │ 終了 │               │
│  ├─────┼────────┼────────┼──────┤               │
│  │ 月   │ [✓]   │ 10:00  │ 20:00│               │
│  │ 火   │ []   │ ---  │ ---  │ ← 定休日              │
│  │ 水   │ [✓]   │  10:00  │ 20:00 │       │
│  │ 木   │ [✓]   │ 10:00  │ 20:00│               │
│  │ 金   │ [✓]   │ 10:00  │ 20:00│               │
│  │ 土   │ [✓]   │ 10:00  │ 20:00│     　　　　  │
│  │ 日   │ [✓]   │  10:00  │ 17:00 │ ← 短縮      │
│  └─────┴────────┴────────┴──────┘               │
│                                                  │
│  [保存]                                          │
│                                                  │
│  ─── 臨時の休み/出勤 ───                         │
│  [+ 臨時休みを追加]                              │
│                                                  │
│  ┌──────────┬──────┬────────────┐               │
│  │ 3/25(火) │ 休み │ 体調不良    │ [削除]       │
│  │ 3/30(日) │ 出勤 │ 振替出勤    │ [削除]       │
│  └──────────┴──────┴────────────┘               │
└──────────────────────────────────────────────────┘
```

### 7. ナビゲーションへの追加

ヘッダーに「院営業スケジュール」メニューを追加（管理者権限🔒）。
ヘッダーに「職員勤務スケジュール」メニューを追加（スタッフ共通・権限不要）。

---

## Step B: 突発休み時の既存予約振替候補提示

### 1. フロー

```
管理者が臨時休みを登録（POST /api/schedule-overrides）
  ↓
バックエンドがその日の既存予約を自動チェック
  ↓
影響を受ける予約がある場合:
  レスポンスに affected_reservations を含めて返す
  ↓
フロントエンドが振替モーダルを表示
  ↓
各予約について:
  - 他の施術者で同日同時間に空きがあるか検索
  - 空きがあれば振替候補として提示
  - 空きがなければ「振替先なし（要連絡）」と表示
  ↓
管理者が各予約の処理を選択:
  [振替する] → 旧予約CANCELLED + 新予約CONFIRMED（選択した施術者で）
  [別日に変更] → 変更申請フロー
  [患者に連絡してキャンセル] → キャンセル申請フロー
  [そのまま（対応しない）] → 何もしない
```

### 2. 振替候補検索ロジック

```python
async def find_transfer_candidates(
    db: AsyncSession,
    original_reservation: Reservation,
    override_date: date
) -> list[dict]:
    """
    元の予約と同じ日時・同じ施術時間で、
    他の施術者に空きがあるか検索する。
    
    Returns:
        [
            {
                "practitioner_id": 2,
                "practitioner_name": "施術者A",
                "available": True,
                "note": ""
            },
            {
                "practitioner_id": 3,
                "practitioner_name": "施術者B",
                "available": False,
                "note": "14:00-15:00に鈴木花子様の予約あり"
            }
        ]
    """
    # 1. その日に出勤している他の施術者を取得
    # 2. 各施術者の同時間帯の予約を確認
    # 3. 空いていれば available=True
    # 4. EXCLUDE制約でも最終チェック
```

### 3. API

| Method | Path | 説明 |
|--------|------|------|
| POST | /api/schedule-overrides | 臨時休み登録（レスポンスに影響予約を含む） |
| GET | /api/reservations/transfer-candidates?reservation_id=&target_practitioner_id= | 振替候補検索 |
| POST | /api/reservations/{id}/transfer | 振替実行（旧CANCELLED + 新CONFIRMED） |

#### POST /api/schedule-overrides レスポンス例

```json
{
  "override": {
    "id": 5,
    "practitioner_id": 1,
    "date": "2026-03-25",
    "is_working": false,
    "reason": "体調不良"
  },
  "affected_reservations": [
    {
      "id": 42,
      "patient_name": "田中太郎",
      "start_time": "10:00",
      "end_time": "10:45",
      "menu_name": "骨盤矯正",
      "transfer_candidates": [
        {"practitioner_id": 2, "practitioner_name": "施術者A", "available": true},
        {"practitioner_id": 3, "practitioner_name": "施術者B", "available": false, "note": "10:00-11:00 鈴木花子様"}
      ]
    },
    {
      "id": 43,
      "patient_name": "山田美咲",
      "start_time": "14:00",
      "end_time": "15:00",
      "menu_name": "全身調整",
      "transfer_candidates": [
        {"practitioner_id": 2, "practitioner_name": "施術者A", "available": true},
        {"practitioner_id": 3, "practitioner_name": "施術者B", "available": true}
      ]
    }
  ]
}
```

---

## 実行記録（2026-03-31時点）

### 施術者の時間帯休みフォーム改善
- 時間帯休みの開始/終了デフォルトを固定値ではなく、院の営業時間設定に追従するよう変更
- 入力UIにも営業時間の min/max を適用し、範囲外入力を抑制

### 患者デフォルト設定追加
- patients に `default_menu_id` と `default_duration` を追加
- APIスキーマ（作成/更新/応答）に同項目を反映
- マイグレーション `012_patient_defaults.py` を追加・適用

### 繰り返し予約（一括生成ツール）
- 仕様はシリーズ管理ではなく「一括生成」に限定（親子構造・一括変更は未導入）
- バックエンドに `POST /api/reservations/bulk` を追加
- 頻度（毎週/隔週/毎月）と終了条件（終了日 or 回数）で日付生成
- 個別生成時に競合/休診/不在などの失敗はスキップし、作成件数・スキップ理由を返却

### フロントエンド反映
- 予約フォームに繰り返し予約UI（頻度・終了条件）を追加
- 一括生成結果（成功件数/スキップ詳細）を表示
- 患者選択時に `default_menu_id` / `default_duration` を予約フォームへ自動反映
- 患者編集画面にデフォルトメニュー/デフォルト時間の設定項目を追加

### 検証結果
- backend: テスト 201 passed（既知の日時依存テスト 1 件は deselect）
- 既知の別件: 既存コード由来の TypeScript 未使用変数/既存型不一致が一部残存（今回変更箇所はエラーなし）

### 4. フロントエンド: 振替モーダル

臨時休み登録後に affected_reservations がある場合に自動表示:

```
┌──────────────────────────────────────────────────────┐
│  ⚠️ 院長 3/25(火) 臨時休み — 影響予約: 2件         │
├──────────────────────────────────────────────────────┤
│                                                      │
│  ① 田中太郎 10:00-10:45 骨盤矯正                    │
│     振替先:                                          │
│     [施術者A ✅ 空き] [施術者B ❌ 10:00鈴木様]       │
│     → [施術者Aに振替] [別日に変更] [キャンセル連絡]  │
│                                                      │
│  ② 山田美咲 14:00-15:00 全身調整                     │
│     振替先:                                          │
│     [施術者A ✅ 空き] [施術者B ✅ 空き]              │
│     → [施術者Aに振替] [施術者Bに振替]                │
│       [別日に変更] [キャンセル連絡]                   │
│                                                      │
│  [すべて確認済み — 閉じる]                           │
└──────────────────────────────────────────────────────┘
```

- 各予約ごとに振替先の空き状況を一目で確認
- ワンクリックで振替実行
- 振替不可の場合は「別日に変更」「キャンセル連絡」の選択肢

---
