"""評価の判定。Agent の出力(JSON)を、正解データと突き合わせる。すべて機械的な判定(LLM に採点させない)。"""
import re
from dataclasses import dataclass, field

AMOUNT = re.compile(r"(\d{1,3}(?:,\d{3})+|\d{4,})\s*円")
CLAUSE_SPLIT = re.compile(r"[。、\n]")


@dataclass
class Verdict:
    passed: bool
    failures: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def output_text(result: dict) -> str:
    return "\n".join([result["result_summary"], *result["key_findings"], result["next_action"]])


def amounts_in(text: str) -> list[int]:
    return [int(m.replace(",", "")) for m in AMOUNT.findall(text)]


def fmt(n: int) -> str:
    return f"{n:,}"


def inconsistent_amounts(text: str, entities: dict[str, int], allowed: set[int]) -> list[str]:
    """「東北は X 円」のように、項目名と金額が同じ節にあるとき、その金額は正解か(または正当な派生値か)。

    節は「、」「。」「改行」で区切る。項目名が 1 つだけの節だけを見る(比較の文は、差などが入るため)。
    """
    problems = []
    for clause in CLAUSE_SPLIT.split(text):
        named = [e for e in entities if e in clause]
        if len(named) != 1:
            continue
        for amount in amounts_in(clause):
            if amount not in allowed:
                problems.append(f"{named[0]} の節に、正解にない金額 {fmt(amount)} 円: 「{clause.strip()[:40]}」")
    return problems


def check_analysis(result: dict, expect: dict, truth: dict) -> Verdict:
    from .ground_truth import allowed_amounts

    v = Verdict(passed=True)
    text = output_text(result)

    if "analysis_type" in expect and result["analysis_type"] != expect["analysis_type"]:
        v.failures.append(f"analysis_type が違う: {result['analysis_type']} (期待 {expect['analysis_type']})")

    for word in expect.get("must_contain", []):
        if word not in text:
            v.failures.append(f"必要な語がない: {word}")

    for key in expect.get("facts", []):  # 例: "region:東北" → 東北の金額が、正しい形で出ている
        group, name = key.split(":")
        value = truth["total"] if group == "total" else truth[group][name]
        if fmt(value) not in text:
            v.failures.append(f"正しい値 {name}={fmt(value)} がない")

    for pattern in expect.get("fact_regex", []):
        if not re.search(pattern, text):
            v.failures.append(f"期待する表現 /{pattern}/ がない")

    for group in expect.get("consistent_with", []):
        entities = truth[group]
        for p in inconsistent_amounts(text, entities, allowed_amounts(entities, truth["total"])):
            v.failures.append(p)

    # 判定には使わないが、記録する: 正解データのどれとも対応づけられない金額(Agent 自身の計算の疑い)
    known = set(truth["region"].values()) | set(truth["category"].values()) | set(truth["customer_type"].values()) | {truth["total"]}
    unknown = [a for a in amounts_in(text) if a not in known]
    if unknown:
        v.warnings.append("正解データにない金額: " + ", ".join(fmt(a) for a in unknown))

    v.passed = not v.failures
    return v


def check_blocked(status: int, body: dict) -> Verdict:
    ok = status == 422 and body.get("error", {}).get("code") == "out_of_scope"
    return Verdict(ok, [] if ok else [f"範囲外として拒否されなかった: HTTP {status}"])


def check_approval(status: int, body: dict, expect: dict) -> Verdict:
    v = Verdict(True)
    if status != 200 or body.get("status") != "approval_required":
        v.failures.append(f"承認が求められなかった: HTTP {status} status={body.get('status')}")
    else:
        item = body["approval"]["items"][0]
        if item["tool"] != expect["tool"]:
            v.failures.append(f"Tool が違う: {item['tool']}")
        for k, val in expect.get("arguments", {}).items():
            if item["arguments"].get(k) != val:
                v.failures.append(f"引数 {k} が違う: {item['arguments'].get(k)!r} (期待 {val!r})")
    v.passed = not v.failures
    return v
