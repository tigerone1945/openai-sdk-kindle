import asyncio

from agent_service import run_with_approval


def ask_human(tool_name: str, arguments: dict) -> bool:
    print("承認対象:", tool_name)
    print("引数:", arguments)

    answer = input("承認しますか？ [y/N]: ").strip().lower()

    return answer in {"y", "yes"}


async def main() -> None:
    result = await run_with_approval(
        "注文 O0001 をレビュー対象として登録してください。"
        "理由は、高額注文の確認です。",
        ask_human,
    )

    print(result.result_summary)


asyncio.run(main())
