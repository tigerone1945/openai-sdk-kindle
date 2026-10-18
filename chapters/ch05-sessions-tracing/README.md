# 第5章 SessionsとTracingで会話と実行履歴を管理する

> 状態：**実行確認済み**（2026-10-02、Python 3.13.8 / openai-agents 0.22.3 / pandas 3.0.6 / streamlit 1.64.0、モデルはSDKデフォルトの `gpt-5.6-luna`）。モデル名はSDKの更新で変わるため、出版直前に再確認する。

## 1. Kindle対応章

本書の第5章「SessionsとTracingで会話と実行履歴を管理する」に対応します。この章の完全なソースコードは `src/` にあります（ファイルの案内は `src/README.md`）。実行手順は、この README に記載しています。

## 2. この章で追加するCapability

- SessionsとTracingで会話と実行履歴を管理する
- `SQLiteSession` と `session_id` で、会話の文脈を次の質問へ引き継ぐ（Follow-up が可能）
- `trace()` の `group_id` で、同じ会話の実行を Tracing でまとめて追跡する
- Chat UI（`st.chat_input` / `st.chat_message`）と「新しい会話を開始」

## 3. 前章からの変更点

- 前章（第4章）で残った課題：会話状態と実行履歴がない
- 差分: `run_sales_agent(question)` → `run_sales_agent(question, session_id)`。`SQLiteSession` と `trace()` を追加
- UI を1回実行のフォームから Chat UI に変更。`st.session_state` に `session_id` と表示履歴を保持
- 依存の追加なし（第4章の `streamlit` を使用）

## 4. この章で確認するFile

- `src/agent_service.py`
- `src/app.py`
- `src/snippets/`（本文の説明用の抜粋 4 件。一覧は `src/README.md`）

## 5. 実行方法

リポジトリのルートで実行する（Setup は第1章 README を参照）。

```bash
uv run streamlit run chapters/ch05-sessions-tracing/src/app.py
```

会話履歴は `data/conversations.db`（SQLite）に保存される。このファイルは実行時に生成され、`.gitignore`（`*.db`）でコミット対象外。会話を最初からやり直したいときは、このファイルを削除する。

## 6. Expected Result

- 質問を続けると、前の質問を踏まえた回答が返る（例: 「この会話の最初の質問は何でしたか？」に、最初の質問を答える）
- サイドバーの「新しい会話を開始」の後は、前の会話を覚えていない
- `data/conversations.db` に会話ごとの履歴が保存される（2ターンで6件: 質問2・Tool呼び出し・Tool結果・回答2）
- Tracing に `sales_analysis_chat` というトレースが、会話の `session_id`（`group_id`）付きで記録される

文面は実行ごとに変わる。実行例は [expected_output/example_run.txt](expected_output/example_run.txt)、画面は、[同じ会話での追質問](images/ch05_screen_01_followup.png)と、[新しい会話で同じ質問をした場合（前の会話を参照しない）](images/ch05_screen_02_new_session.png)を参照。

注意:
- Session には Tool の出力（売上データの写し）が保存される。Tracing も、既定では Tool の入出力を記録する。記録したくない場合は `RunConfig(trace_include_sensitive_data=False)` を使う（本文「Tracing Data Governance」参照）。
- Streamlit の `AppTest` で複数ターンを自動テストすると `Event loop is closed` になることがある。実ブラウザでは発生しなかった。

## 7. 次章で変更される点

- 安全境界がInstructionsだけ
- 次章：`../ch06-guardrails/`
