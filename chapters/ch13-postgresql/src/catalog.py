"""業務上の定義:どのTable・Join・切り口を許すか。データベースの種類に依存しない。

SQLを組み立てるRepositoryも、Agentに見せるToolも、ここだけを見る(第9章のJoin Governance)。
"""

BUSINESS_TABLES = ("orders", "customers", "products")

ALLOWED_JOINS: dict[tuple[str, str], tuple[str, str]] = {
    ("orders", "customers"): ("customer_id", "customer_id"),
    ("orders", "products"): ("product_id", "product_id"),
}

# Semantic Layer(最小形): 「切り口」という業務用語を、(Table, 列)に結びつける。
DIMENSIONS: dict[str, tuple[str, str]] = {
    "category": ("products", "category"),
    "customer_type": ("customers", "customer_type"),
    "region": ("orders", "region"),
}

MAX_REVIEW_ORDERS = 50
MAX_PREVIEW_ROWS = 20


def resolve_join(left: str, right: str) -> tuple[str, str] | None:
    """許可されたJoinなら、(leftの結合キー, rightの結合キー)を返す。"""
    if (left, right) in ALLOWED_JOINS:
        return ALLOWED_JOINS[(left, right)]

    if (right, left) in ALLOWED_JOINS:
        right_key, left_key = ALLOWED_JOINS[(right, left)]
        return left_key, right_key

    return None


def require_table(name: str) -> str:
    """SQLに埋め込む識別子は、許可リストにあるものだけ通す。"""
    if name not in BUSINESS_TABLES:
        raise ValueError(f"許可されていないTableです: {name}")
    return name


def clamp(value: int, upper: int) -> int:
    """取得件数に上限を付ける(Agentが決めた値を、そのまま信用しない)。"""
    return max(1, min(value, upper))
