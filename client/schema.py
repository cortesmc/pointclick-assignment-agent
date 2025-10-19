from pydantic import BaseModel, Field, ValidationError, field_validator
from typing import Optional, Literal, Any, Dict, List

CommandName = Literal["navigate", "waitFor", "query", "click", "type", "scroll", "switchTab", "screenshot", "ping"]

class Command(BaseModel):
    id: str = Field(..., description="Unique id string")
    cmd: CommandName
    args: Dict[str, Any] = Field(default_factory=dict)

    @field_validator("args")
    @classmethod
    def validate_args(cls, v: Dict[str, Any]) -> Dict[str, Any]:
        # Light sanity checks for known commands
        return v or {}

class Plan(BaseModel):
    steps: List[Command]

def validate_plan_json(obj: Any) -> "Plan":
    """
    Accepts dict or list (common model outputs). Converts into Plan.
    Raises ValidationError if invalid.
    """
    if isinstance(obj, list):
        # List of commands
        return Plan(steps=[Command(**x) for x in obj])
    if isinstance(obj, dict) and "steps" in obj:
        return Plan(**obj)
    # Some models return {"plan": [...]}
    if isinstance(obj, dict) and "plan" in obj:
        return Plan(steps=[Command(**x) for x in obj["plan"]])
    raise ValidationError([f"Unrecognized plan format: {type(obj)}"], Plan)
