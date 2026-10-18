# 第7章 Human-in-the-Loopで人の判断を組み込む

> 状態：**実行確認済み**（2026-10-06、Python 3.13.8 / openai-agents 0.22.3 / pandas 3.0.6、モデルはSDKデフォルトの `gpt-5.6-luna`）。モデル名はSDKの更新で変わるため、出版直前に再確認する。

## 1. Kindle対応章

本書の第7章「Human-in-the-Loopで人の判断を組み込む」に対応します。この章の完全なソースコードは `src/` にあります（ファイルの案内は `src/README.md`）。実行手順は、この README に記載しています。

## 2. この章で追加するCapability

- Human-in-the-Loopで人の判断を組み込む
- 状態を変更する Tool（`create_review_request`）に `needs_approval=True` を付け、人の承認があるまで実行しない
- 承認（approve）・却下（reject）・再開（resume）、承認フローの監査ログ（`data/audit_log.jsonl`）
- Tool 内での入力検証と重複防止（承認されても省略しない）

## 3. 前章からの変更点

- 前章（第6章）で残った課題：止めるだけで人へ判断を戻せない
- 差分: `create_review_request`（承認が必要な Tool）、`write_audit_log`、`run_with_approval` を追加
- Guardrail を逐次（`run_in_parallel=False`）に変更し、許可例に「注文IDを指定したレビュー依頼の登録」を追加
- UI は CLI（`main.py`）のみ。画面版は作らない

## 4. この章で確認するFile

- `src/agent_service.py`（第6章のコードに承認フローを加えた完全版）
- `src/main.py`（CLI の承認画面）
- `src/snippets/`（本文の説明用の抜粋 5 件。一覧は `src/README.md`）

## 5. 実行方法

リポジトリのルートで実行する（Setup は第1章 README を参照）。

```bash
uv run python chapters/ch07-hitl/src/main.py
```

承認の問い合わせで `y` を入力すると登録され、`n` を入力すると登録されない。実行時に次のファイルが生成される（どちらも `.gitignore` で除外）。

- `data/review_requests.csv` … 登録されたレビュー依頼
- `data/audit_log.jsonl` … 承認の依頼・承認・却下・実行の記録

やり直したいときは、この2ファイルを削除する。

## 6. Expected Result

- `y` を入力: 「承認対象: create_review_request」と引数が表示され、登録される。`data/review_requests.csv` に `O0001` が入る
- `n` を入力: 登録されず、「実行承認されませんでした」という趣旨の応答が返る
- 読み取りだけの質問（例: 「地域別の売上を分析してください」）では、承認を求められない
- 存在しない注文ID・二重登録は、承認されても Tool が拒否する（監査ログに `approved` はあるが `executed` はない）

文面は実行ごとに変わる。実行例は [expected_output/example_run.txt](expected_output/example_run.txt) を参照。

注意:
- Instructions や Tool の docstring に「承認が必要」と書かない。書くと、Agent が Tool を呼ぶ前に自分で止まり、承認の問い合わせが人に届かないことが多い（実測: 1/6。書かなければ 10/10）。
- 中断した実行は `RunState` を文字列に保存でき、別プロセスで復元して再開できる。保存した状態には質問と Tool 引数が含まれる。
- 同一プロセスで `asyncio.run()` の後に `Runner.run_sync()` を呼ぶと `Event loop is closed` になる（第6章参照）。この章のコードは `Runner.run`（非同期）だけを使う。

## 7. 次章で変更される点

- 業務データがCSVのまま。永続化・更新の基盤がない
- 次章：`../ch08-sqlite/`
