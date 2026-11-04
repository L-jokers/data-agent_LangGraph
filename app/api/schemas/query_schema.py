from pydantic import BaseModel, Field


class QuerySchema(BaseModel):
    query: str = Field(min_length=1)
    session_id: str | None = Field(default=None, min_length=1)
    clarification_id: str | None = Field(default=None, min_length=1)
