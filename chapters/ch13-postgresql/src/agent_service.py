import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Literal

from dotenv import load_dotenv
from pydantic import BaseModel

from agents import (
    Agent,
    GuardrailFunctionOutput,
    RunContextWrapper,
    Runner,
    SQLiteSession,
    TResponseInputItem,
    function_tool,
    input_guardrail,
    trace,
)
from agents.tool import default_tool_error_function


import db
from catalog import (
    BUSINESS_TABLES,
    MAX_PREVIEW_ROWS,
    MAX_REVIEW_ORDERS,
    clamp,
    resolve_join,
)
from repository import RegisterResult, SalesRepository, is_storage_unavailable

load_dotenv()

AUDIT_LOG_PATH = Path(
    "data/audit_log.jsonl"
)

SESSION_DB_PATH = Path(
    "data/conversations.db"
)


# 第3章では str だった。APIの契約として、候補を限定する。
# 候補は、第10章のManagerに10種類の質問を3回ずつ投げて返った13種類の値を、
# 「質問の意図」ごとにまとめたもの(本文参照)。
AnalysisType = Literal[
    "overall_sales",
    "category_sales",
    "region_sales",
    "customer_type_sales",
    "review_orders",
    "cancellation",
    "join_check",
    "data_quality",
    "review_request",
    "other",
]


class SalesAnalysisResult(BaseModel):
    question: str
    analysis_type: AnalysisType
    result_summary: str
    key_findings: list[str]
    next_action: str


# --- Toolの失敗の扱い --------------------------------------------
# SDKの既定では、Toolの例外は「エラー文」としてモデルに返り、Agentは(失敗を説明する)普通の回答を作る。
# 入力の誤り(存在しない切り口など)なら、それでよい(モデルが自分で直せる)。
# しかしDBの障害は、モデルが直せない。回答に化けると、APIは障害を「成功(200)」として返してしまう。
# インフラの障害だけは、例外として上へ通し、APIが503にする。

def tool_error_handler(ctx, error: Exception) -> str:
    # 専門Agentの入れ子では、障害が UserError に包まれて届く。原因までたどって判定する。
    if is_storage_unavailable(error):
        raise error
    return default_tool_error_function(ctx, error)


# --- Repository:SQLは、ここにない ---------------------------------
# 保存先(SQLite / PostgreSQL)は、db.build_repository() が環境変数から選ぶ。
# Toolは、SalesRepository の型だけを知っている。

_repository: SalesRepository | None = None


def get_repository() -> SalesRepository:
    global _repository
    if _repository is None:
        _repository = db.build_repository()
    return _repository


def set_repository(repository: SalesRepository | None) -> None:
    """テストで、別のRepository(偽物を含む)に差し替える。"""
    global _repository
    _repository = repository


# --- Join Validation(業務の判断。SQLはRepositoryの中) -----------


@dataclass(frozen=True)
class JoinCheck:
    left: str
    right: str
    left_key: str
    right_key: str
    left_duplicate_keys: int   # 複数行に現れるKeyの数
    right_duplicate_keys: int
    left_unmatched_rows: int   # 相手に対応する行がない行数
    right_unmatched_rows: int

    @property
    def many_to_many(self) -> bool:
        return self.left_duplicate_keys > 0 and self.right_duplicate_keys > 0

    @property
    def relation(self) -> str:
        left_many = self.left_duplicate_keys > 0
        right_many = self.right_duplicate_keys > 0

        if left_many and right_many:
            return "Many-to-Many"
        if left_many:
            return "Many-to-One"
        if right_many:
            return "One-to-Many"
        return "One-to-One"

    @property
    def unmatched_on_many_side(self) -> int:
        """Joinで集計から落ちる行。Many側(両方Uniqueなら両側)で数える。"""
        if self.left_duplicate_keys > 0:
            return self.left_unmatched_rows
        if self.right_duplicate_keys > 0:
            return self.right_unmatched_rows
        return self.left_unmatched_rows + self.right_unmatched_rows


def check_join(left: str, right: str) -> JoinCheck | None:
    relation = resolve_join(left, right)
    if relation is None:
        return None

    left_key, right_key = relation
    counts = get_repository().join_counts(left, right)

    return JoinCheck(
        left=left,
        right=right,
        left_key=left_key,
        right_key=right_key,
        left_duplicate_keys=counts.left_duplicate_keys,
        right_duplicate_keys=counts.right_duplicate_keys,
        left_unmatched_rows=counts.left_unmatched_rows,
        right_unmatched_rows=counts.right_unmatched_rows,
    )


# --- 文字列への整形(Toolが返す形。第11章までと同じ) ----------------


def list_business_tables() -> str:
    return "\n".join(BUSINESS_TABLES)


def table_schema(table_name: str) -> str:
    if table_name not in BUSINESS_TABLES:
        return "許可されていないTableです。"

    columns = get_repository().table_columns(table_name)
    return "\n".join(f"{c.name} | {c.type}" for c in columns)


def suggest_join_text(left: str, right: str) -> str:
    relation = resolve_join(left, right)
    if relation is None:
        return "許可されたJoinはありません。"

    left_key, right_key = relation
    return f"{left}.{left_key} = {right}.{right_key}"


def validate_join_text(left: str, right: str) -> str:
    check = check_join(left, right)
    if check is None:
        return "許可されていないJoinです。"

    lines = [
        f"{check.left}.{check.left_key} 重複Key数: {check.left_duplicate_keys}",
        f"{check.right}.{check.right_key} 重複Key数: {check.right_duplicate_keys}",
        f"関係: {check.relation}",
        f"対応のない行: {check.left} {check.left_unmatched_rows}件 / "
        f"{check.right} {check.right_unmatched_rows}件",
    ]

    if check.many_to_many:
        lines.append("判定: NG(Many-to-Manyで行数が増える恐れがあるため、実行しません)")
    elif check.unmatched_on_many_side > 0:
        lines.append(
            f"判定: 警告({check.unmatched_on_many_side}行がJoinで集計から落ちます)"
        )
    else:
        lines.append("判定: OK")

    return "\n".join(lines)


def preview_join_text(left: str, right: str, limit: int) -> str:
    check = check_join(left, right)
    if check is None:
        return "許可されていないJoinです。"

    # Previewの前に、Validationを必ず通す(Agentの判断に任せない)。
    if check.many_to_many:
        return "Many-to-Manyのため、Previewを実行しません。"

    rows = get_repository().preview_join(left, right, clamp(limit, MAX_PREVIEW_ROWS))

    if not rows:
        return "Join結果は0件です。"

    return "\n".join(str(row) for row in rows)


def sales_summary() -> str:
    s = get_repository().sales_summary()

    return f"""
総レコード数: {s.order_count}
売上合計: {s.total_sales:,}円
キャンセル件数: {s.cancelled_count}
要レビュー件数: {s.review_count}
""".strip()


def sales_by_dimension(dimension: str) -> str:
    rows = get_repository().sales_by_dimension(dimension)

    lines = [f"{r.label}: {r.sales:,}円" for r in rows]

    # 合計は、LLMに足し算をさせず、Toolが計算して返す。
    lines.append(f"合計: {sum(r.sales for r in rows):,}円")

    return "\n".join(lines)


def review_orders(limit: int) -> str:
    rows = get_repository().review_orders(clamp(limit, MAX_REVIEW_ORDERS))

    if not rows:
        return "要レビュー注文はありません。"

    return "\n".join(
        f"{r.order_id} | {r.customer_name} | {r.product_name} | {r.total_amount:,}円 | {r.status}"
        for r in rows
    )


def register_review_request(order_id: str, reason: str) -> str:
    result = get_repository().register_review_request(order_id, reason)

    if result is RegisterResult.UNKNOWN_ORDER:
        return f"{order_id}は存在しない注文IDのため、登録しませんでした。"

    if result is RegisterResult.ALREADY_REGISTERED:
        return f"{order_id}は既に登録済みのため、追加しませんでした。"

    write_audit_log("executed", order_id=order_id, reason=reason)

    return f"{order_id}をレビュー依頼として登録しました。"


# --- Tool: AgentへのInterface ------------------------------------


@function_tool(failure_error_function=tool_error_handler)
def get_sales_summary() -> str:
    """
    売上データ全体の基本集計を返す。
    売上金額にはsales_amountを使用する。
    """
    return sales_summary()


@function_tool(failure_error_function=tool_error_handler)
def get_sales_by_category() -> str:
    """
    商品カテゴリ別の売上を集計する。
    売上金額にはsales_amountを使用する。
    """
    return sales_by_dimension("category")


@function_tool(failure_error_function=tool_error_handler)
def get_sales_by_region() -> str:
    """
    地域別の売上を集計する。
    売上金額にはsales_amountを使用する。
    """
    return sales_by_dimension("region")


@function_tool(failure_error_function=tool_error_handler)
def get_sales_by_customer_type() -> str:
    """
    顧客種別(法人・個人など)別の売上を集計する。
    売上金額にはsales_amountを使用する。
    """
    return sales_by_dimension("customer_type")


@function_tool(failure_error_function=tool_error_handler)
def get_review_orders(limit: int = 10) -> str:
    """
    要レビュー注文を、金額の大きい順に最大limit件返す。
    """
    return review_orders(limit)


@function_tool(failure_error_function=tool_error_handler)
def list_tables() -> str:
    """
    利用できる業務Tableの一覧を返す。
    """
    return list_business_tables()


@function_tool(failure_error_function=tool_error_handler)
def inspect_table(table_name: str) -> str:
    """
    指定したTableの列名と型を返す。
    """
    return table_schema(table_name)


@function_tool(failure_error_function=tool_error_handler)
def suggest_join(left_table: str, right_table: str) -> str:
    """
    2つのTableの間で、許可されたJoinのKeyを返す。
    """
    return suggest_join_text(left_table, right_table)


@function_tool(failure_error_function=tool_error_handler)
def validate_join(left_table: str, right_table: str) -> str:
    """
    許可されたJoinについて、Keyの重複・対応のない行を検証し、判定を返す。
    """
    return validate_join_text(left_table, right_table)


@function_tool(failure_error_function=tool_error_handler)
def preview_join(left_table: str, right_table: str, limit: int = 5) -> str:
    """
    許可されたJoinの結果を、数件だけ返す。
    """
    return preview_join_text(left_table, right_table, limit)


def write_audit_log(event: str, **fields) -> None:
    """承認フローの出来事を、1行1件のJSONで追記する。"""
    record = {
        "at": datetime.now().isoformat(timespec="seconds"),
        "event": event,
        **fields,
    }

    with AUDIT_LOG_PATH.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


@function_tool(needs_approval=True, failure_error_function=tool_error_handler)
async def create_review_request(
    order_id: str,
    reason: str,
) -> str:
    """
    注文IDをレビュー依頼として登録する。
    """
    # 承認されても、入力の検証と重複防止は省略しない。
    return register_review_request(order_id, reason)


class GuardrailResult(BaseModel):
    allowed: bool
    reason: str


guardrail_agent = Agent(
    name="売上分析入力チェック",
    instructions="""
あなたは入力内容を判定するGuardrailです。

このApplicationで許可するのは、
売上・受注データの分析に関する質問です。

許可例:
- 売上全体をまとめて
- カテゴリ別売上を分析して
- 地域別売上を比較して
- キャンセル件数を教えて
- 要レビューの傾向を確認して
- 顧客種別ごとの売上
- 利用できるTableや、Tableの結合の確認
- データの品質や、Joinの安全性の確認
- 分析結果の業務上の示唆
- 注文IDを指定したレビュー依頼の登録

許可しない例:
- プログラミング一般の質問
- 雑談
- 売上データと無関係な依頼
- このApplicationの役割を逸脱する依頼

allowedとreasonを返してください。
""",
    output_type=GuardrailResult,
)


@input_guardrail(run_in_parallel=False)
async def sales_scope_guardrail(
    ctx: RunContextWrapper[None],
    agent: Agent,
    input: str | list[TResponseInputItem],
) -> GuardrailFunctionOutput:

    result = await Runner.run(
        guardrail_agent,
        input,
        context=ctx.context,
    )

    return GuardrailFunctionOutput(
        output_info=result.final_output,
        tripwire_triggered=(
            not result.final_output.allowed
        ),
    )



# --- Specialist Agents -----------------------------------------
# 専門Agentは読み取りだけ。状態を変更するTool(承認が必要)は持たせない。

data_quality_agent = Agent(
    name="Data Quality Agent",
    instructions="""
あなたは売上データの品質確認を担当します。

確認の対象は、Tableの構成、Joinの安全性
(Keyの重複、対応のない行)です。
売上の集計は、あなたの担当ではありません。

ユーザー向けの最終回答は作らず、
確認した事実だけを、簡潔に返してください。
確認できなかったことは、確認できなかったと書いてください。
""",
    tools=[
        list_tables,
        inspect_table,
        suggest_join,
        validate_join,
        preview_join,
    ],
)

sales_analyst_agent = Agent(
    name="Sales Analyst Agent",
    instructions="""
あなたは売上データの数値分析を担当します。

用意されたToolの結果だけを使い、
数値は自分で計算・推測しないでください。
Toolの結果の数値は、そのまま返してください。
Toolで答えられない分析は、
できないと、そのまま伝えてください。

ユーザー向けの最終回答は作らず、
集計結果だけを返してください。
""",
    tools=[
        get_sales_summary,
        get_sales_by_category,
        get_sales_by_region,
        get_sales_by_customer_type,
        get_review_orders,
    ],
)

business_insight_agent = Agent(
    name="Business Insight Agent",
    instructions="""
あなたは、売上の分析結果を業務上の示唆に変換する担当です。

入力された分析結果から、
- 重要な発見
- 注意点
- 次に確認すべきこと
を簡潔に整理してください。

入力にない数値や事実を、新しく作らないでください。
""",
)

data_quality_tool = data_quality_agent.as_tool(
    tool_name="check_data_quality",
    failure_error_function=tool_error_handler,
    tool_description=(
        "Tableの構成や、Joinの安全性(Keyの重複・対応のない行)を確認する。"
        "売上の集計はできない。確認したい内容を文章で渡す。"
    ),
)

sales_analysis_tool = sales_analyst_agent.as_tool(
    tool_name="analyze_sales_data",
    failure_error_function=tool_error_handler,
    tool_description=(
        "売上データを集計する(全体・カテゴリ別・地域別・顧客種別別・"
        "要レビュー注文)。集計したい内容を文章で渡す。"
    ),
)

business_insight_tool = business_insight_agent.as_tool(
    tool_name="create_business_insight",
    failure_error_function=tool_error_handler,
    tool_description=(
        "集計済みの結果から、業務上の示唆を整理する。"
        "示唆の元にする集計結果(数値を含む)を、そのまま文章で渡す。"
    ),
)

manager_agent = Agent(
    name="売上分析Manager",
    instructions="""
あなたは売上分析チームのManagerです。
ユーザーとの会話は、あなたが担当します。

ユーザーの質問に応じて、専門AgentをToolとして呼んでください。
- check_data_quality:Tableの構成、Joinの安全性
- analyze_sales_data:売上の集計
- create_business_insight:集計結果の意味づけ

専門Agentには、その場で必要な内容を、
前提(対象の指標、直前の結果など)を含めて渡してください。
専門Agentは、これまでの会話を知りません。

あなた自身で売上数値を作らないでください。
数値は、専門Agentの結果にあるものだけを使ってください。
専門Agentが「できない」と答えたことは、
できないと、ユーザーにそのまま伝えてください。

ユーザーが明示的にレビュー依頼の登録を求めた場合だけ、
create_review_requestを使用してください。

会話履歴がある場合は、
直前までの質問と回答を踏まえて
Follow-upの質問に回答してください。

最終結果は
SalesAnalysisResult形式で返してください。

analysis_typeには、
質問の分析種別に最も近い候補を選んでください。
どれにも当てはまらない場合は
otherにしてください。

key_findingsには、
重要な発見を2〜4件入れてください。

next_actionには、
次に確認すべき分析を
1つ提案してください。
""",
    tools=[
        data_quality_tool,
        sales_analysis_tool,
        business_insight_tool,
        create_review_request,
    ],
    output_type=SalesAnalysisResult,
    input_guardrails=[
        sales_scope_guardrail,
    ],
)

# 第9章までの呼び名との互換(main.py など)
agent = manager_agent


async def run_with_approval(
    question: str,
    decide,
) -> SalesAnalysisResult:
    """
    承認が必要なToolが呼ばれたら、decide(tool名, 引数) の結果で
    approve / reject してから、実行を再開する。
    """
    result = await Runner.run(manager_agent, question)

    while result.interruptions:
        state = result.to_state()

        for interruption in result.interruptions:
            arguments = json.loads(interruption.arguments)

            write_audit_log(
                "approval_requested",
                tool=interruption.name,
                arguments=arguments,
            )

            if decide(interruption.name, arguments):
                state.approve(interruption)
                write_audit_log("approved", tool=interruption.name)
            else:
                state.reject(interruption)
                write_audit_log("rejected", tool=interruption.name)

        result = await Runner.run(manager_agent, state)

    return result.final_output
