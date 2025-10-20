import argparse
import asyncio
import json
import sys
from typing import Any, Dict, List, Optional

from planner import plan_from_text
from llm_planner import plan_with_llm
from executor import run_plan


def _detect_scenario(plan_steps: List[Dict[str, Any]]) -> str:
    for s in plan_steps:
        if s.get("cmd") == "navigate" or s.get("cmd") == "openTab":
            url = (s.get("args") or {}).get("url", "")
            if "huggingface.co/papers" in url:
                return "hf"
            if "mail.google.com" in url and ("promo" in url or "#search/" in url):
                return "gmail_promo"
    return "generic"


def _pretty_hf(plan_steps: List[Dict[str, Any]], results_steps: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """
    Optional helper to render a {title,url} when you're *not* in --silent mode.
    Keeps backward-compat for non-silent demos. Safe to skip entirely.
    """
    if len(results_steps) < 2:
        return None
    plan_by_id = {s["id"]: s for s in plan_steps if "id" in s}

    # Find any query that fetched an href to /papers/
    href = None
    for step in results_steps:
        sid = step.get("id")
        cmd = plan_by_id.get(sid, {})
        if cmd.get("cmd") != "query":
            continue
        args = cmd.get("args") or {}
        if args.get("attr") == "href" and "/papers/" in (args.get("selector") or ""):
            arr = (step.get("data") or {}).get("results") or []
            href = arr[0] if arr else None
            if href:
                break

    if not href:
        return None

    # Try to find a sibling title query result after that
    title = None
    for step in reversed(results_steps):
        sid = step.get("id")
        cmd = plan_by_id.get(sid, {})
        if cmd.get("cmd") != "query":
            continue
        sel = (cmd.get("args") or {}).get("selector", "")
        if ("a[href^='/papers/']" in sel and ("h3" in sel or "h4" in sel or "span" in sel)) or (":is(h3,h4)" in sel):
            arr = (step.get("data") or {}).get("results") or []
            if arr and (arr[0] or "").strip():
                title = arr[0].strip()
                break

    url = f"https://huggingface.co{href}" if href.startswith("/") else href
    return {"title": title, "url": url}


def _pretty_gmail_unread(plan_steps: List[Dict[str, Any]], results_steps: List[Dict[str, Any]]) -> Optional[List[Dict[str, Any]]]:
    """
    Optional pretty pairing of senders+subjects when not in --silent mode.
    """
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
        if not step.get("ok"):
            continue
        sid = step.get("id")
        cmd = plan_by_id.get(sid, {})
        if cmd.get("cmd") != "query":
            continue
        sel = (cmd.get("args") or {}).get("selector", "")
        arr = (step.get("data") or {}).get("results") or []
        if not senders and any(s in sel for s in sender_selectors):
            senders = arr
        if not subjects and any(s in sel for s in subject_selectors):
            subjects = arr

    def clean_sender(s):
        s = (s or "").strip()
        return None if s.isdigit() else s

    senders = [s for s in (clean_sender(x) for x in senders) if s]
    n = min(len(senders), len(subjects))
    if n == 0:
        return None
    return [{"from": senders[i], "subject": subjects[i]} for i in range(n)]


def _print_plan(steps: List[Dict[str, Any]]) -> None:
    print("Plan:")
    for s in steps:
        print("-", json.dumps(s, ensure_ascii=False))


def main() -> None:
    parser = argparse.ArgumentParser(description="Natural language → browser actions (Point&Click orchestrator)")
    parser.add_argument("task", type=str, help="What should the agent do? (quotes recommended)")

    parser.add_argument("--planner", choices=["rule", "llm"], default="rule", help="Choose the planning strategy.")
    parser.add_argument("--provider", choices=["openai", "anthropic"], default="openai",
                        help="LLM provider (used when --planner llm).")
    parser.add_argument("--model", type=str, default=None, help="LLM model override (e.g., gpt-4o-mini).")

    parser.add_argument("--raw", action="store_true", help="Only print raw JSON result (no pretty extras).")
    parser.add_argument("--silent", action="store_true", help="Do not print plan/result; just execute.")
    parser.add_argument("--no-pretty", action="store_true", help="Disable scenario pretty output (non-silent mode only).")

    args = parser.parse_args()

    # 1) Choose planner with graceful fallback to rule
    try:
        if args.planner == "llm":
            plan = plan_with_llm(args.task, provider=args.provider, model=args.model)
        else:
            plan = plan_from_text(args.task)
    except Exception as e:
        if not args.silent:
            print(f"[planner] LLM planner failed ({e}); falling back to rule-based.")
        plan = plan_from_text(args.task)

    plan_steps = [s.model_dump() for s in plan.steps]

    # 2) Optionally show the plan
    if not args.silent and not args.raw:
        _print_plan(plan_steps)

    # 3) Execute
    result = asyncio.run(run_plan(plan_steps))

    # 4) Console output policy
    if args.silent:
        return

    if args.raw:
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return

    print("\nResult:")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if not result.get("ok"):
        return

    # 5) Optional pretty output (HF/Gmail) unless disabled
    if not args.no_pretty:
        scenario = _detect_scenario(plan_steps)
        if scenario == "hf":
            pretty = _pretty_hf(plan_steps, result["results"])
            if pretty:
                print("\nLatest paper:")
                print(json.dumps(pretty, ensure_ascii=False, indent=2))
        elif scenario == "gmail_promo":
            promos = _pretty_gmail_unread(plan_steps, result["results"])
            if promos:
                print("\nUnread promotions (up to 10):")
                print(json.dumps(promos, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(130)
