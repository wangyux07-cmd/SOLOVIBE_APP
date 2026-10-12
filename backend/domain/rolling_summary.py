"""Lossy historical narrative, never the authority for constraints or actions."""
from pydantic import BaseModel, ConfigDict, Field


class SummaryDraft(BaseModel):
    model_config = ConfigDict(extra='forbid')
    topic: str = Field(max_length=400)
    preference_reasons: list[str] = Field(default_factory=list, max_length=8)
    rejected_ideas: list[str] = Field(default_factory=list, max_length=8)
    unresolved_questions: list[str] = Field(default_factory=list, max_length=5)

    def bounded(self) -> dict:
        result = self.model_dump()
        if sum(len(str(value)) for value in result.values()) > 2200:
            raise ValueError('summary too long')
        return result
