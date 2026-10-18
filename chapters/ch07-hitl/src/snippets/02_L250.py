import csv
from datetime import datetime
from pathlib import Path


REVIEW_REQUESTS_PATH = Path(
    "data/review_requests.csv"
)


@tool(needs_approval=True)
async def create_review_request(
    order_id: str,
    reason: str,
) -> str:
    """
    注文IDをレビュー依頼として登録する。
    このToolは人の承認後にのみ実行する。
    """

    file_exists = REVIEW_REQUESTS_PATH.exists()

    with REVIEW_REQUESTS_PATH.open(
        "a",
        newline="",
        encoding="utf-8-sig",
    ) as f:
        writer = csv.writer(f)

        if not file_exists:
            writer.writerow(
                [
                    "created_at",
                    "order_id",
                    "reason",
                ]
            )

        writer.writerow(
            [
                datetime.now().isoformat(
                    timespec="seconds"
                ),
                order_id,
                reason,
            ]
        )

    return (
        f"{order_id}をレビュー依頼として"
        "登録しました。"
    )
