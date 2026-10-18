from pydantic import BaseModel


class AnalysisRequest(BaseModel):
    question: str
    session_id: str


class AnalysisResponse(BaseModel):
    analysis_type: str
    result_summary: str
    key_findings: list[str]
    next_action: str
