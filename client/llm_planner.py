# Turns a natural-language task into a strict JSON plan via LLM.
# Guardrails:
# - Only allowed commands
# - Don't add Gmail time filters unless the user requests it

import json, os, re, uuid
from typing import Any, Optional
from dotenv import load_dotenv
from schema import validate_plan_json, Plan, Command

load_dotenv(dotenv_path="./.env")

ALLOWED_CMDS = [
    "navigate", "waitFor", "query", "click", "type",
    "scroll", "switchTab", "screenshot", "ping", "openTab"
]

SYSTEM_PROMPT = """You are a planning engine that outputs ONLY JSON (array or {"steps":[...]}).
RULES:
- Only use: navigate, waitFor, query, click, type, scroll, switchTab, screenshot, ping, openTab.
- Prefer 'openTab' over 'navigate' when the goal is to show a new page to the user.
- Do NOT print or summarize results; the controller will show opened pages.
- Use 'query' only to fetch hrefs or small pieces needed for the next action.
- Do NOT add date/time filters unless the USER explicitly requested a timeframe (e.g., 'last 14 days', 'since 2025-07-01').
- If timeframe is requested for Gmail, map it to:
  last N days → newer_than:Nd
  last N weeks → newer_than:(N*7)d
  last N months → newer_than:Nm
  since YYYY-MM-DD → after:YYYY/MM/DD
- JSON ONLY. No explanations.
"""

FEWSHOTS = [
  # Hugging Face papers search then extract first /papers/ href
  ("open hugging face papers and get the latest link",
   [
     {"id":"a1","cmd":"openTab","args":{"url":"https://huggingface.co/papers","active":True}},
     {"id":"a2","cmd":"waitFor","args":{"selector":"main section article","timeoutMs":15000}},
     {"id":"a3","cmd":"waitFor","args":{"selector":"input[type='search']","timeoutMs":8000}},
     {"id":"a4","cmd":"type","args":{"selector":"input[type='search']","text":"UI Agents","submit":False}},
     {"id":"a5","cmd":"waitFor","args":{"selector":"main section article","timeoutMs":8000}},
     {"id":"a6","cmd":"query","args":{"selector":"main section article:nth-of-type(1) a[href^='/papers/']","all":False,"attr":"href"}}
   ]),
  # Gmail with NO timeframe
  ("open gmail promotions and list unread promotions",
   [
     {"id":"g1","cmd":"openTab","args":{"url":"https://mail.google.com/mail/u/0/#search/category%3Apromotions%20is%3Aunread","active":True}},
     {"id":"g2","cmd":"waitFor","args":{"selector":"div[role='main']","timeoutMs":20000}},
     {"id":"g3","cmd":"waitFor","args":{"selector":"tr.zA","timeoutMs":25000}}
   ]),
  # Gmail with explicit timeframe (teaches the difference)
  ("open gmail promotions and list unread promotions from the last 14 days",
   [
     {"id":"g1","cmd":"openTab","args":{"url":"https://mail.google.com/mail/u/0/#search/category%3Apromotions%20is%3Aunread%20newer_than%3A14d","active":True}},
     {"id":"g2","cmd":"waitFor","args":{"selector":"div[role='main']","timeoutMs":20000}},
     {"id":"g3","cmd":"waitFor","args":{"selector":"tr.zA","timeoutMs":25000}}
   ]),
]

def _mk_id() -> str:
    return uuid.uuid4().hex[:8]

def _coerce_ids(plan: Plan) -> Plan:
    # Ensure each step has an id
    steps = []
    for s in plan.steps:
        if not getattr(s, "id", None):
            s.id = _mk_id()
        steps.append(s)
    return Plan(steps=steps)

def _sanitize_commands(plan: Plan) -> Plan:
    # Drop any commands not allowed
    return Plan(steps=[s for s in plan.steps if s.cmd in ALLOWED_CMDS])

def _json_from_text(txt: str) -> Any:
    # Extract first JSON object/array
    t = txt.strip()
    if t.startswith("{") or t.startswith("["):
        return json.loads(t)
    m = re.search(r"(\{.*\}|\[.*\])", txt, re.S)
    if m:
        return json.loads(m.group(1))
    raise ValueError("No JSON found in model output")

def _openai_complete(prompt: str, model: str) -> str:
    from openai import OpenAI
    client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
    resp = client.chat.completions.create(
        model=model, temperature=0.1,
        messages=[{"role":"system","content":SYSTEM_PROMPT},
                  {"role":"user","content":prompt}]
    )
    return resp.choices[0].message.content

def _anthropic_complete(prompt: str, model: str) -> str:
    import anthropic
    client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
    msg = client.messages.create(
        model=model, max_tokens=1500, temperature=0.1,
        system=SYSTEM_PROMPT, messages=[{"role":"user","content":prompt}]
    )
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
        lines.append("")
    lines.append(f"USER: {task}")
    lines.append("ASSISTANT:")
    return "\n".join(lines)

def plan_with_llm(task: str, provider: str = "openai", model: Optional[str] = None) -> Plan:
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
        # Last resort: a no-op ping
        plan = Plan(steps=[Command(id=_mk_id(), cmd="ping", args={})])

    plan = _coerce_ids(plan)
    plan = _sanitize_commands(plan)
    return plan
