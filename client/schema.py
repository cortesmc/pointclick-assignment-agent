# Plan/Command schema to validate LLM outputs. Keeps execution safe.

from pydantic import BaseModel, Field, ValidationError
from typing import Literal, Any, Dict, List

CommandName = Literal[
    "navigate", "waitFor", "query", "click", "type",
    "scroll", "switchTab", "screenshot", "ping", "openTab"
]

class Command(BaseModel):
    id: str = Field(..., description="Unique id string")
    cmd: CommandName
    args: Dict[str, Any] = Field(default_factory=dict)

class Plan(BaseModel):
    steps: List[Command]

def validate_plan_json(obj: Any) -> "Plan":
    # Accept either {"steps":[...]} or bare list [...]
    if isinstance(obj, list):
        return Plan(steps=[Command(**x) for x in obj])
    if isinstance(obj, dict) and "steps" in obj:
        return Plan(**obj)
    if isinstance(obj, dict) and "plan" in obj:
        return Plan(steps=[Command(**x) for x in obj["plan"]])
    raise ValidationError([f"Unrecognized plan format: {type(obj)}"], Plan)
