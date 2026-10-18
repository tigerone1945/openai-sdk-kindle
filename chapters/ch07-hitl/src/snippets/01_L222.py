from agents.decorators import tool


@tool(needs_approval=True)
async def create_review_request(
    order_id: str,
    reason: str,
) -> str:
    ...
