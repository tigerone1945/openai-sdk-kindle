from pydantic import BaseModel


class SalesAnalysisResult(BaseModel):
    question: str
    analysis_type: str
    result_summary: str
    key_findings: list[str]
    next_action: str
