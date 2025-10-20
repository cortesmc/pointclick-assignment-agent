import json, os, re, uuid
from typing import Any, Dict, List, Optional, Tuple

from dotenv import load_dotenv
from schema import validate_plan_json, Plan, Command

load_dotenv()

ALLOWED_CMDS = [
    "navigate", "waitFor", "query", "click", "type",
    "scroll", "switchTab", "screenshot", "ping", "openTab"
]

SYSTEM_PROMPT = """You are a planning engine ...
RULES:
- Only use these commands: navigate, waitFor, query, click, type, scroll, switchTab, screenshot, ping, openTab.
- Prefer 'openTab' (new tab) over 'navigate' when the goal is to show a page to the user.
- Do NOT print results; just open the relevant tabs. Use 'query' only to fetch an href for a subsequent 'openTab'.
- Do NOT add any date/time filter unless the USER explicitly requested a timeframe (e.g., 'last 14 days', 'last 3 months', 'since 2025-07-01').
- When a timeframe IS requested for Gmail, use the corresponding Gmail search operator:
  • last N days → newer_than:Nd
  • last N weeks → newer_than:(N*7)d
  • last N months → newer_than:Nm
  • since YYYY-MM-DD → after:YYYY/MM/DD
- JSON ONLY. No explanations.
"""

FEWSHOTS = [
  (
    "open hugging face papers and get the latest link",
    [
      {"id":"a1","cmd":"openTab","args":{"url":"https://huggingface.co/papers","active":True}},
      {"id":"a2","cmd":"waitFor","args":{"selector":"main section article","timeoutMs":15000}},
      {"id":"a3","cmd":"waitFor","args":{"selector":"input[type='search']","timeoutMs":8000}},
      {"id":"a4","cmd":"type","args":{"selector":"input[type='search']","text":"UI Agents","submit":False}},
      {"id":"a5","cmd":"waitFor","args":{"selector":"main section article","timeoutMs":8000}},
      {"id":"a6","cmd":"query","args":{"selector":"main section article:nth-of-type(1) a[href^='/papers/']","all":False,"attr":"href"}}
    ],
  ),
  # No timeframe requested → NO newer_than
  (
    "open gmail promotions and list unread promotions",
    [
      {"id":"g1","cmd":"openTab","args":{"url":"https://mail.google.com/mail/u/0/#search/category%3Apromotions%20is%3Aunread","active":True}},
      {"id":"g2","cmd":"waitFor","args":{"selector":"div[role='main']","timeoutMs":20000}},
      # Optional: drop this wait and just query; leaving it here is fine if your client tolerates empty.
      {"id":"g3","cmd":"waitFor","args":{"selector":"tr.zA","timeoutMs":25000}}
    ],
  ),
  # Timeframe requested → DO add newer_than
  (
    "open gmail promotions and list unread promotions from the last 14 days",
    [
      {"id":"g1","cmd":"openTab","args":{"url":"https://mail.google.com/mail/u/0/#search/category%3Apromotions%20is%3Aunread%20newer_than%3A14d","active":True}},
      {"id":"g2","cmd":"waitFor","args":{"selector":"div[role='main']","timeoutMs":20000}},
      {"id":"g3","cmd":"waitFor","args":{"selector":"tr.zA","timeoutMs":25000}}
    ],
  ),
]

def _mk_id() -> str:
    return uuid.uuid4().hex[:8]

def _coerce_ids(plan: Plan) -> Plan:
    # Ensure every step has an id; if not, assign.
    fixed = []
    for s in plan.steps:
        if not getattr(s, "id", None):
            s.id = _mk_id()
        fixed.append(s)
    return Plan(steps=fixed)

def _sanitize_commands(plan: Plan) -> Plan:
    # Drop any commands not in allowlist
    kept = []
    for s in plan.steps:
        if s.cmd not in ALLOWED_CMDS:
            continue
        kept.append(s)
    return Plan(steps=kept)

def _json_from_text(txt: str) -> Any:
    """Extract first JSON object/array from text (LLM safeguard)."""
    # Quick path: pure JSON
    t = txt.strip()
    if t.startswith("{") or t.startswith("["):
        return json.loads(t)
    # Fallback: first {...} or [...]
    m = re.search(r"(\{.*\}|\[.*\])", txt, re.S)
    if m:
        return json.loads(m.group(1))
    raise ValueError("No JSON found in model output")

def _openai_complete(prompt: str, model: str) -> str:
    from openai import OpenAI
    client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
    # Use Chat Completions (widely available)
    resp = client.chat.completions.create(
        model=model,
        temperature=0.1,
        messages=[
            {"role":"system","content":SYSTEM_PROMPT},
            {"role":"user","content":prompt},
        ],
    )
    return resp.choices[0].message.content

def _anthropic_complete(prompt: str, model: str) -> str:
    import anthropic
    client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
    msg = client.messages.create(
        model=model,
        max_tokens=1500,
        temperature=0.1,
        system=SYSTEM_PROMPT,
        messages=[{"role":"user","content":prompt}],
    )
    # Concatenate text blocks
    out = ""
    for b in msg.content:
        if b.type == "text":
            out += b.text
    return out

def _build_fewshot_prompt(task: str) -> str:
    lines = []
    for user, steps in FEWSHOTS:
        lines.append(f"USER: {user}")
        lines.append("ASSISTANT:")
        lines.append(json.dumps(steps, ensure_ascii=False))
        lines.append("")  # spacer
    lines.append(f"USER: {task}")
    lines.append("ASSISTANT:")
    return "\n".join(lines)

def plan_with_llm(task: str, provider: str = "openai", model: Optional[str] = None) -> Plan:
    """
    provider: "openai" | "anthropic"
    model:
      - openai: e.g., "gpt-4o-mini" (fast) or "gpt-4o"
      - anthropic: e.g., "claude-3-5-sonnet-latest"
    """
    provider = (provider or "openai").lower()
    if provider == "openai":
        model = model or os.getenv("OPENAI_MODEL", "gpt-4o-mini")
        if not os.getenv("OPENAI_API_KEY"):
            raise RuntimeError("OPENAI_API_KEY missing")
        raw = _openai_complete(_build_fewshot_prompt(task), model)
    elif provider == "anthropic":
        model = model or os.getenv("ANTHROPIC_MODEL", "claude-3-5-sonnet-latest")
        if not os.getenv("ANTHROPIC_API_KEY"):
            raise RuntimeError("ANTHROPIC_API_KEY missing")
        raw = _anthropic_complete(_build_fewshot_prompt(task), model)
    else:
        raise ValueError(f"Unknown provider: {provider}")

    try:
        obj = _json_from_text(raw)
        plan = validate_plan_json(obj)
    except Exception:
        # Last-resort: produce a minimal safe plan (no-op ping)
        plan = Plan(steps=[Command(id=_mk_id(), cmd="ping", args={})])

    plan = _coerce_ids(plan)
    plan = _sanitize_commands(plan)
    return plan
