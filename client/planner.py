import re, uuid
from schema import Plan, Command

def _id():
    return str(uuid.uuid4())[:8]

def plan_from_text(task: str) -> Plan:
    t = task.lower().strip()

    # Simple intents (expand as you like)
    if "hugging face" in t or "huggingface" in t:
        # open HF papers and get latest link
        steps = [
            Command(id=_id(), cmd="navigate", args={"url": "https://huggingface.co/papers"}),
            Command(id=_id(), cmd="waitFor", args={"selector": "main section article", "timeoutMs": 15000}),
            Command(id=_id(), cmd="query", args={"selector": "main section article:nth-of-type(1) a[href^='/papers/']", "all": False, "attr": "href"}),
        ]
        return Plan(steps=steps)

    # Wikipedia search: “search wikipedia for X”
    m = re.search(r"wikipedia.* for (.+)", t)
    if m:
        q = m.group(1).strip()
        steps = [
            Command(id=_id(), cmd="navigate", args={"url": "https://en.wikipedia.org/wiki/Special:Search"}),
            Command(id=_id(), cmd="waitFor", args={"selector": "#searchInput", "timeoutMs": 15000}),
            Command(id=_id(), cmd="type",     args={"selector": "#searchInput", "text": q, "submit": True}),
            Command(id=_id(), cmd="waitFor",  args={"selector": "#mw-content-text", "timeoutMs": 15000}),
            Command(id=_id(), cmd="scroll",   args={"to": "bottom"}),
            Command(id=_id(), cmd="scroll",   args={"to": "top"}),
        ]
        return Plan(steps=steps)

    if "gmail" in t and ("promo" in t or "promotion" in t or "promotions" in t):
        steps = [
            # Open Promotions (assumes logged-in test account)
            Command(id=_id(), cmd="navigate", args={"url": "https://mail.google.com/mail/u/0/#category/promo"}),
            Command(id=_id(), cmd="waitFor", args={"selector": "div[role='main']", "timeoutMs": 20000}),
            Command(id=_id(), cmd="waitFor", args={"selector": "tr.zA", "timeoutMs": 20000}),
            # Try primary sender selector first, then two fallbacks
            Command(id=_id(), cmd="query", args={"selector": "tr.zA.zE span.yX.xY .yW span", "all": True, "limit": 10}),
            Command(id=_id(), cmd="query", args={"selector": "tr.zA.zE .yW span[dir='auto']", "all": True, "limit": 10}),
            Command(id=_id(), cmd="query", args={"selector": "tr.zA.zE .yW > span", "all": True, "limit": 10}),
            # Subject selector + fallback
            Command(id=_id(), cmd="query", args={"selector": "tr.zA.zE span.bog", "all": True, "limit": 10}),
            Command(id=_id(), cmd="query", args={"selector": "tr.zA.zE .bog span", "all": True, "limit": 10}),
        ]
        return Plan(steps=steps)


    # Default: just navigate to what looks like a URL
    url_match = re.search(r"(https?://\S+)", task)
    if url_match:
        steps = [
            Command(id=_id(), cmd="navigate", args={"url": url_match.group(1)}),
            Command(id=_id(), cmd="waitFor",  args={"selector": "body", "timeoutMs": 10000}),
        ]
        return Plan(steps=steps)

    # Fallback minimal no-op
    return Plan(steps=[Command(id=_id(), cmd="ping", args={})])
