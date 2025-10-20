import re, uuid
from schema import Plan, Command

def _id():
    return str(uuid.uuid4())[:8]

def plan_from_text(task: str) -> Plan:
    t = task.lower().strip()
    
    if "hugging face" in t or "huggingface" in t:
        # Interpret “find the latest paper about UI Agents”
        steps = [
            # Open HF Papers (focused tab)
            Command(id=_id(), cmd="openTab", args={"url": "https://huggingface.co/papers", "active": True}),
            Command(id=_id(), cmd="waitFor", args={"selector": "main section article", "timeoutMs": 15000}),

            # Type into the on-page search (keeps everything in-page)
            Command(id=_id(), cmd="waitFor", args={"selector": "input[type='search']", "timeoutMs": 8000}),
            Command(id=_id(), cmd="type",     args={"selector": "input[type='search']", "text": "UI Agents", "submit": False}),
            Command(id=_id(), cmd="waitFor",  args={"selector": "main section article", "timeoutMs": 8000}),

            # Grab first result href and open it in a NEW TAB (no stdout)
            Command(id=_id(), cmd="query",   args={
                "selector": "main section article:nth-of-type(1) a[href^='/papers/']",
                "all": False, "attr": "href"
            }),
            # The executor won’t print, but we still need to open the URL:
            # Orchestrator converts the last query’s href to an absolute URL and fires an `openTab`.
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

    # Gmail search
    if "gmail" in t and ("promo" in t or "promotion" in t or "promotions" in t):
        # Open Promotions with a search filter: unread + last 3 months
        q = "category:promotions is:unread newer_than:3m"
        url = "https://mail.google.com/mail/u/0/#search/" + q.replace(" ", "%20")
        steps = [
            Command(id=_id(), cmd="openTab", args={"url": url, "active": True}),
            Command(id=_id(), cmd="waitFor", args={"selector": "div[role='main']", "timeoutMs": 20000}),
            Command(id=_id(), cmd="waitFor", args={"selector": "tr.zA", "timeoutMs": 15000}),
            # Stop here — the page shows the results to the user; no scraping/printing.
        ]
        return Plan(steps=steps)

    # Default: just navigate to what looks like a URL
    url_match = re.search(r"(https?://\S+)", task)
    if url_match:
        steps = [
            Command(id=_id(), cmd="openTab", args={"url": url_match.group(1), "active": True}),
            Command(id=_id(), cmd="waitFor", args={"selector": "body", "timeoutMs": 10000}),
        ]
        return Plan(steps=steps)

    # Fallback minimal no-op
    return Plan(steps=[Command(id=_id(), cmd="ping", args={})])
