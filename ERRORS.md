# 開発エラー台帳

## 2026-09-04: ホストPowerShellでpytestを直接実行できない

- 症状: `pytest` がコマンドとして認識されない。
- 原因: Pythonテスト環境はホストではなくDockerバックエンド側にある。
- 手順: このリポジトリのbackendテストはCompose定義を確認し、`docker compose run --rm backend pytest ...` で実行する。
- 状態: L1（初回記録）

## 2026-09-04: backend全体テストの既知4失敗

- 症状: 全体テストは `4 failed / 401 passed`。失敗は `test_daily_report` 1件、`test_integration` 1件、`test_patients` 2件。
- 原因: SQLiteがPostgreSQL専用JSONBを生成できない既存のテスト分離問題と、既存AsyncMockのcoroutine取り扱い。
- 判定: 変更前の `main` と同じ4テストが同じ原因で失敗する。LINE対象テストは `137 passed`。
- 手順: LINE変更の回帰判定では、上記4件以外の失敗増加がないことを比較する。
- 状態: 既知ベースライン（今回の変更対象外）
