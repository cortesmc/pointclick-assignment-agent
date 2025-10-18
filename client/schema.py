from pydantic import BaseModel, Field
from typing import Optional, Literal, Any, Dict

CommandName = Literal["navigate", "waitFor", "query", "click", "type", "scroll", "ping"]

class Command(BaseModel):
    id: str = Field(..., description="Unique id string")
    cmd: CommandName
    args: Dict[str, Any] = Field(default_factory=dict)

class Plan(BaseModel):
    steps: list[Command]
