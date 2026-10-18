"""Multi-Agentの責務の境界を、LLMなしで確認する。

実行(リポジトリのルートから。先に第9章の取り込みでDBを作る):
    uv run python chapters/ch09-multitable/src/scripts/normalize_sales_db.py
    uv run --with pytest pytest chapters/ch10-multi-agent/tests -q
"""
import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent.parent


def load_module(name: str, path: Path):
    """章ごとに同名の agent_service.py があるため、一意な名前で読み込む。"""
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


multi = load_module("ch10_agent_service", ROOT / "ch10-multi-agent/src/agent_service.py")
single = load_module("ch09_agent_service_ref", ROOT / "ch09-multitable/src/agent_service.py")

SPECIALISTS = [
    multi.data_quality_agent,
    multi.sales_analyst_agent,
    multi.business_insight_agent,
]


def tool_names(agent) -> set[str]:
    return {t.name for t in agent.tools}


def test_manager_owns_conversation_and_side_effects():
    assert tool_names(multi.manager_agent) == {
        "check_data_quality",
        "analyze_sales_data",
        "create_business_insight",
        "create_review_request",
    }
    assert multi.manager_agent.output_type is multi.SalesAnalysisResult
    assert multi.manager_agent.input_guardrails


def test_specialists_have_no_side_effect_tool():
    """状態を変更するTool(承認が必要)は、Managerだけが持つ。"""
    for agent in SPECIALISTS:
        assert "create_review_request" not in tool_names(agent), agent.name
        assert not any(getattr(t, "needs_approval", False) is True for t in agent.tools), agent.name


def test_specialist_tool_sets_do_not_overlap():
    sets = [tool_names(a) for a in SPECIALISTS]
    for i, a in enumerate(sets):
        for b in sets[i + 1:]:
            assert a.isdisjoint(b)


def test_responsibilities_are_separated():
    assert tool_names(multi.data_quality_agent) == {
        "list_tables", "inspect_table", "suggest_join", "validate_join", "preview_join"
    }
    assert "get_sales_summary" in tool_names(multi.sales_analyst_agent)
    assert not any("join" in n for n in tool_names(multi.sales_analyst_agent))
    assert tool_names(multi.business_insight_agent) == set()  # 数値を作らせないため、Toolを持たせない


def test_no_agent_has_the_whole_toolbox():
    """分割の目的:どのAgentも、第9章の単一Agentより少ないToolしか持たない。"""
    total = len(single.agent.tools)
    for agent in [multi.manager_agent, *SPECIALISTS]:
        assert len(agent.tools) < total, agent.name


def test_instructions_do_not_mention_approval():
    """第7章の教訓:承認の話をInstructionsやTool説明に書かない(承認の問い合わせが届かなくなる)。"""
    texts = [a.instructions for a in [multi.manager_agent, *SPECIALISTS]]
    texts += [t.description for t in multi.manager_agent.tools]
    assert not any("承認" in text for text in texts)


def test_agent_tools_pass_text_only():
    """専門Agentは、会話履歴を受け取らない。入力は文章1つだけ。"""
    for name in ("check_data_quality", "analyze_sales_data", "create_business_insight"):
        tool = next(t for t in multi.manager_agent.tools if t.name == name)
        assert list(tool.params_json_schema["properties"]) == ["input"]


def test_manager_is_told_specialists_have_no_context():
    assert "これまでの会話を知りません" in multi.manager_agent.instructions


@pytest.fixture
def db_available():
    if not multi.SALES_DB_PATH.exists():
        pytest.skip("先に第9章の normalize_sales_db.py を実行してください")


def test_data_layer_has_not_drifted_from_chapter_9(db_available):
    """章ごとに複製したData Accessが、第9章と同じ結果を返す(複製の乖離を検出)。"""
    assert multi.sales_summary() == single.sales_summary()
    for dim in multi.DIMENSIONS:
        assert multi.sales_by_dimension(dim) == single.sales_by_dimension(dim)
    assert multi.review_orders(5) == single.review_orders(5)
    assert multi.validate_join_text("orders", "customers") == single.validate_join_text(
        "orders", "customers"
    )
    assert multi.ALLOWED_JOINS == single.ALLOWED_JOINS
