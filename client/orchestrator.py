import argparse
import asyncio
import json
import sys
from typing import Any, Dict, List, Optional

from planner import plan_from_text
from executor import run_plan


def _detect_scenario(plan_steps: List[Dict[str, Any]]) -> str:
    """Heuristically detect which scenario this plan is for."""
    for s in plan_steps:
        if s.get("cmd") == "navigate":
            url = (s.get("args") or {}).get("url", "")
            if "huggingface.co/papers" in url:
                return "hf"
            if "mail.google.com" in url and "promo" in url:
                return "gmail_promo"
    return "generic"


def _pretty_hf(plan_steps: List[Dict[str, Any]], results_steps: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Use the known HF selectors to pull {title,url} from the last two HF queries."""
    if len(results_steps) < 4:
        return None

    # Map id -> original command to check selectors
    plan_by_id = {s["id"]: s for s in plan_steps if "id" in s}

    try:
        href_step = results_steps[-2]
        title_step = results_steps[-1]
        # Ensure these were queries to the HF selector to avoid misfire
        href_cmd = plan_by_id.get(href_step["id"], {})
        title_cmd = plan_by_id.get(title_step["id"], {})
        href_sel = (href_cmd.get("args") or {}).get("selector", "")
        title_sel = (title_cmd.get("args") or {}).get("selector", "")
        if "/papers/" not in href_sel or "/papers/" not in title_sel:
            return None

        hrefs = href_step["data"]["results"]
        titles = title_step["data"]["results"]
        href = hrefs[0] if hrefs else None
        title = titles[0] if titles else None
        if not href and not title:
            return None
        url = f"https://huggingface.co{href}" if href and href.startswith("/papers/") else href
        return {"title": title, "url": url}
    except Exception:
        return None


def _pretty_gmail_unread(plan_steps, results_steps):
    plan_by_id = {s["id"]: s for s in plan_steps if "id" in s}

    sender_selectors = [
        "tr.zA.zE span.yX.xY .yW span",
        "tr.zA.zE .yW span[dir='auto']",
        "tr.zA.zE .yW > span",
    ]
    subject_selectors = [
        "tr.zA.zE span.bog",
        "tr.zA.zE .bog span",
    ]

    senders, subjects = [], []
    for step in results_steps:
        if not step.get("ok"): continue
        sid = step.get("id")
        cmd = plan_by_id.get(sid, {})
        if cmd.get("cmd") != "query": continue
        sel = (cmd.get("args") or {}).get("selector", "")
        arr = (step.get("data") or {}).get("results") or []
        if not senders and any(s in sel for s in sender_selectors):
            senders = arr
        if not subjects and any(s in sel for s in subject_selectors):
            subjects = arr

    # filter obvious numeric badge artifacts like "2"
    def clean_sender(s):
        s = (s or "").strip()
        return None if s.isdigit() else s

    senders = [clean_sender(s) for s in senders]
    senders = [s for s in senders if s]  # drop None/empty

    n = min(len(senders), len(subjects))
    if n == 0: return None
    return [{"from": senders[i], "subject": subjects[i]} for i in range(n)]


def print_plan(steps: List[Dict[str, Any]]) -> None:
    print("Plan:")
    for s in steps:
        print("-", json.dumps(s, ensure_ascii=False))


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Natural language → browser actions (Point&Click assignment orchestrator)"
    )
    parser.add_argument("task", type=str, help="What should the agent do? (quotes recommended)")
    parser.add_argument("--raw", action="store_true", help="Only print raw JSON result (no pretty extras).")
    parser.add_argument("--timeout", type=int, default=30, help="Per-step recv timeout (seconds).")
    parser.add_argument("--adapter-wait", type=int, default=45, help="How long to wait for the adapter to connect (seconds).")
    args = parser.parse_args()

    plan = plan_from_text(args.task)
    plan_steps = [s.model_dump() for s in plan.steps]

    print_plan(plan_steps)

    result = asyncio.run(run_plan(plan_steps))
    if args.raw:
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return

    print("\nResult:")
    print(json.dumps(result, ensure_ascii=False, indent=2))

    if not result.get("ok"):
        return

    scenario = _detect_scenario(plan_steps)

    if scenario == "hf":
        pretty = _pretty_hf(plan_steps, result["results"])
        if pretty:
            print("\nLatest paper:")
            print(json.dumps(pretty, ensure_ascii=False, indent=2))

    if scenario == "gmail_promo":
        promos = _pretty_gmail_unread(plan_steps, result["results"])
        if promos:
            print("\nUnread promotions (up to 10):")
            print(json.dumps(promos, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(130)
