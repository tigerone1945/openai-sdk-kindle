"""質問・回答を、どこにも残さない方針: ログ(test_observability)・Tracing・OpenAI 側の保存。"""
import re
from types import SimpleNamespace

from agents import Agent, ModelSettings

from conftest import SRC, M

obs, service, core = M.observability, M.service, M.agent_service


def test_every_agent_in_the_application_is_set_not_to_store_responses():
    agents = {n: v for n, v in vars(core).items() if isinstance(v, Agent)}
    assert {"guardrail_agent", "data_quality_agent", "sales_analyst_agent", "business_insight_agent", "manager_agent"} <= set(agents)
    assert service.PRIVATE_AGENTS and set(service.PRIVATE_AGENTS) == set(agents)
    for name, agent in agents.items():
        assert agent.model_settings.store is False, name


def test_policy_keeps_other_model_settings():
    ns = SimpleNamespace(a=Agent(name="a", model_settings=ModelSettings(temperature=0.3)))
    obs.apply_privacy_policy(ns)
    assert ns.a.model_settings.store is False and ns.a.model_settings.temperature == 0.3


def test_policy_can_be_turned_off_for_debugging(monkeypatch):
    monkeypatch.setenv("OPENAI_STORE_RESPONSES", "true")
    ns = SimpleNamespace(a=Agent(name="a"))
    assert obs.apply_privacy_policy(ns) == [] and ns.a.model_settings.store is None


def test_policy_ignores_non_agents_and_is_idempotent():
    ns = SimpleNamespace(a=Agent(name="a"), x=1, y="s")
    assert obs.apply_privacy_policy(ns) == ["a"] and obs.apply_privacy_policy(ns) == ["a"]


def test_container_image_turns_tracing_sensitive_data_off_by_default():
    text = (SRC / "Dockerfile.api").read_text()
    assert re.search(r"^\s*OPENAI_AGENTS_TRACE_INCLUDE_SENSITIVE_DATA=false", text, re.M)
    from agents import RunConfig
    import os
    old = os.environ.get("OPENAI_AGENTS_TRACE_INCLUDE_SENSITIVE_DATA")
    os.environ["OPENAI_AGENTS_TRACE_INCLUDE_SENSITIVE_DATA"] = "false"
    try:
        assert RunConfig().trace_include_sensitive_data is False
    finally:
        os.environ.pop("OPENAI_AGENTS_TRACE_INCLUDE_SENSITIVE_DATA") if old is None else os.environ.update(OPENAI_AGENTS_TRACE_INCLUDE_SENSITIVE_DATA=old)
