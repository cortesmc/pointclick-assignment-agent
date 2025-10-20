# CLI entrypoint:
# - Builds a plan with the LLM
# - Executes it
# - Prints raw JSON result or nothing (silent)

import argparse, asyncio, json, sys
from typing import Any, Dict, List
from llm_planner import plan_with_llm
from executor import run_plan

def _print_plan(steps: List[Dict[str, Any]]) -> None:
    print("Plan:")
    for s in steps:
        print("-", json.dumps(s, ensure_ascii=False))

def main() -> None:
    p = argparse.ArgumentParser(description="Natural language → browser actions (LLM planner)")
    p.add_argument("task", type=str, help="What should the agent do? (quotes recommended)")
    p.add_argument("--provider", choices=["openai", "anthropic"], default="openai")
    p.add_argument("--model", type=str, help="Model name (e.g., gpt-4o-mini)")
    p.add_argument("--raw", action="store_true", help="Print only raw JSON result")
    p.add_argument("--silent", action="store_true", help="No output; just execute")
    args = p.parse_args()

    # 1) Plan with LLM only (no rule-based fallback)
    plan = plan_with_llm(args.task, provider=args.provider, model=args.model)
    plan_steps = [s.model_dump() for s in plan.steps]

    # 2) Optionally show plan
    if not args.silent and not args.raw:
        _print_plan(plan_steps)

    # 3) Execute
    result = asyncio.run(run_plan(plan_steps))

    # 4) Output policy
    if args.silent:
        return
    print(json.dumps(result, ensure_ascii=False, indent=2) if args.raw else "\nResult:\n" + json.dumps(result, ensure_ascii=False, indent=2))

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(130)
