from agents import Agent


data_quality_agent = Agent(
    name="Data Quality Agent",
    instructions="""
あなたは売上データの品質確認を担当します。

確認対象:
- 欠損
- 重複
- 不正値
- Join Key
- Table間整合性

ユーザー向けの最終回答は作らず、
Manager Agentが利用しやすい形で
簡潔に結果を返してください。
""",
    tools=[
        list_tables,
        inspect_table,
        validate_join,
        preview_join,
    ],
)
