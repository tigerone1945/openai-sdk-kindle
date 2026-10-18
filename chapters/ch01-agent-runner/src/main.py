from pathlib import Path

import pandas as pd
from dotenv import load_dotenv
from agents import Agent, Runner

load_dotenv()

CSV_PATH = Path("data/raw/ai_agent_practice_sales.csv")

df = pd.read_csv(CSV_PATH)

dataset_profile = f"""
このCSVは売上・受注データです。

レコード数:
{len(df)}

列名:
{", ".join(df.columns)}

注文日の最小値:
{df["order_date"].min()}

注文日の最大値:
{df["order_date"].max()}
"""

agent = Agent(
    name="売上分析アシスタント",
    instructions="""
あなたは売上データ分析を支援するAIアシスタントです。

与えられたDataset Profileを読み、
最初に確認すべき分析観点を3つ提案してください。

まだ実データの数値集計は行わず、
どの観点を確認すべきかだけを説明してください。
""",
)

prompt = f"""
以下が分析対象データの概要です。

{dataset_profile}

このデータを分析するとしたら、
最初に確認すべき観点を3つ提案してください。
"""

result = Runner.run_sync(
    agent,
    prompt,
)

print(result.final_output)
