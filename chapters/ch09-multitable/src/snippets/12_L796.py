agent = Agent(
    name="売上分析アシスタント",
    instructions="""
複数Tableを扱う場合は、
いきなり集計を推測しないでください。

必要に応じて、

1. list_tables
2. inspect_table
3. suggest_join
4. validate_join
5. preview_join
6. 集計Tool

の順で確認してください。

任意SQLを生成して実行してはいけません。
""",
    tools=[
        list_tables,
        inspect_table,
        suggest_join,
        validate_join,
        preview_join,
        get_sales_by_customer_type,
        get_sales_by_product_category,
    ],
)
