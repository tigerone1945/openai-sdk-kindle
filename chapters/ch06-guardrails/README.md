# 第6章 Guardrailsで安全境界を作る

> 状態：**実行確認済み**（2026-10-02、Python 3.13.8 / openai-agents 0.22.3 / pandas 3.0.6 / streamlit 1.64.0、モデルはSDKデフォルトの `gpt-5.6-luna`）。モデル名はSDKの更新で変わるため、出版直前に再確認する。

## 1. Kindle対応章

本書の第6章「Guardrailsで安全境界を作る」に対応します。この章の完全なソースコードは `src/` にあります（ファイルの案内は `src/README.md`）。実行手順は、この README に記載しています。

## 2. この章で追加するCapability

- Guardrailsで安全境界を作る
- Input Guardrail で、売上・受注データの分析と関係のない質問を、Agent が動く前に止める（tripwire）
- UI が `InputGuardrailTripwireTriggered` を受けて、利用者へ案内を表示する

## 3. 前章からの変更点

- 前章（第5章）で残った課題：安全境界がInstructionsだけ
- 差分: `GuardrailResult` / `guardrail_agent` / `sales_scope_guardrail` を追加し、メインの Agent に `input_guardrails=[...]` を登録
- `app.py` に `InputGuardrailTripwireTriggered` の処理を追加
- 依存の追加なし

## 4. この章で確認するFile

- `src/agent_service.py`（第5章のコードに Guardrail を追加した完全版）
- `src/app.py`（第5章の UI に tripwire の処理を追加した完全版）
- `src/snippets/`（本文の説明用の抜粋 11 件。一覧は `src/README.md`）

## 5. 実行方法

リポジトリのルートで実行する（Setup は第1章 README を参照）。

```bash
uv run streamlit run chapters/ch06-guardrails/src/app.py
```

## 6. Expected Result

- 売上分析の質問（例: 「地域別の売上を分析してください」）は、通常どおり回答が返る
- 範囲外の質問（例: 「Pythonでゲームを作ってください」）は、Agent が回答を作らずに止まり、「売上・受注データの分析に関する質問だけを扱います」という案内が出る
- 止められた後でも、次の売上分析の質問は正常に動く

文面は実行ごとに変わる。実行例は [expected_output/example_run.txt](expected_output/example_run.txt)、画面は、[範囲外の質問が止められた画面](images/ch06_screen_01_blocked.png)と、[止められた後の売上分析の質問](images/ch06_screen_02_after_block.png)を参照。

注意:
- Guardrail の判定は LLM なので、境界の質問では結果が揺れる。会話そのものについての質問（「この会話の最初の質問は何でしたか？」）は、5回とも拒否された。
- Input Guardrail には会話履歴が渡される。同じ質問でも、会話の中と単体とで結果が変わる。
- Guardrail 自体が失敗すると、例外として止まる（回答は返らない）。画面には `st.exception(e)` でエラー詳細が出るので、本番では一般的なメッセージだけにする。
- SDK の既定では、Guardrail とメインの Agent は並列で動く（`run_in_parallel=True`）。拒否される質問でも、止まる前にメインの Agent が Tool を呼ぶことがある。状態を変更する Tool を足す第7章以降で見直す。
- 拒否された質問も `data/conversations.db` に保存される。
- 同一プロセスで `asyncio.run()` の後に `Runner.run_sync()` を呼ぶと `Event loop is closed` になる。検証スクリプトを書くときに注意する。

## 7. 次章で変更される点

- 止めるだけで人へ判断を戻せない
- 次章：`../ch07-hitl/`
