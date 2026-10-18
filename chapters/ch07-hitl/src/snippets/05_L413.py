import asyncio

from agents import Agent, Runner


async def main() -> None:
    result = await Runner.run(
        agent,
        """
注文 O0001 をレビュー対象として登録してください。
理由は、高額注文の確認です。
""",
    )

    while result.interruptions:
        state = result.to_state()

        for interruption in result.interruptions:
            print(
                "承認対象:",
                interruption.name,
            )
            print(
                "引数:",
                interruption.arguments,
            )

            answer = input(
                "承認しますか？ [y/N]: "
            ).strip().lower()

            if answer in {
                "y",
                "yes",
            }:
                state.approve(
                    interruption
                )
            else:
                state.reject(
                    interruption
                )

        result = await Runner.run(
            agent,
            state,
        )

    print(result.final_output)


asyncio.run(main())
