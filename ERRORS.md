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
- 最新確認: LINE inbox段階導入後は `4 failed / 411 passed`、LINE対象は `145 passed`。失敗名は同一。
- 手順: LINE変更の回帰判定では、上記4件以外の失敗増加がないことを比較する。
- 状態: 既知ベースライン（今回の変更対象外）

## 2026-09-04: `python -c` で複数行async関数がSyntaxError

- 症状: PowerShellから`python -c`へセミコロン後の`async def`と文字列`\n`を渡すと構文エラーになる。
- 原因: compound statementはセミコロン後に置けず、PowerShell文字列内の`\n`もPythonコードの改行にならない。
- 手順: 複数行の実行確認はPowerShellのhere-stringを`docker compose run --rm -T backend python -`へ標準入力する。
- 状態: L1（初回記録）

## 2026-09-04: 部分importしたDBスニペットでSQLAlchemy mapper未登録

- 症状: `app.api.line`だけをimportしてORMクエリを実行すると、`ReservationColor`を解決できず`InvalidRequestError`になる。
- 原因: 通常のFastAPI起動時に行われる全モデルimportを通さず、SQLAlchemy mapper registryが不完全な状態でクエリをコンパイルした。
- 手順: DBスニペットは先に`import app.models`して全モデルを登録するか、実API/pytest経路で検証する。
- 状態: L1（初回記録）

## 2026-09-04: 共有ターミナルのcwd変化で`git -C ..`がリポジトリ外を参照

- 症状: ターミナルが既にリポジトリルートへ移動していたため、`git -C .. diff`が親フォルダを参照して`Not a git repository`になった。
- 原因: 前回コマンドのcwdが維持される共有ターミナルで、`..`をbackend基準だと仮定した。
- 手順: Git操作前に`$repo = git rev-parse --show-toplevel`でルートを取得し、以後は`git -C $repo ...`を使う。
- 状態: L2（相対cwd前提の再発。以後ルートをコマンドで確定する）

## 2026-09-04: デプロイ前の`DATABASE_URL`がローカル接続だった

- 症状: URLは設定済みだが`IsLocal=True`で、本番のautopilot対象者件数確認に使用できなかった。
- 追加エラー: psqlは`ssl`クエリパラメータを受け付けず、`ssl=disable`が残ると`invalid URI query parameter`になる。
- 手順: DB操作前に接続先を値非表示でlocal/Render判定する。psqlではasyncpgスキームを変換し、`ssl=require|disable`も`sslmode=require|disable`へ変換する。
- 状態: push前で停止。本番影響なし。

## 2026-09-04: PowerShellの`foreach`直後のpipeでParserError

- 症状: 1行内の`foreach (...) { ... } | Format-Table`で`An empty pipe element is not allowed`になった。
- 原因: 文としての`foreach`出力をそのまま同一構文のpipelineへ接続した。
- 手順: 結果を`$rows = @(...foreach...)`へ格納してから`$rows | Format-Table`する。
- 状態: L1（初回記録）
