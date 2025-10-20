import asyncio, json
import websockets
from typing import Dict, Any
from utils import log_event
from urllib.parse import urljoin

URI = "ws://127.0.0.1:8765"

def _maybe_follow_href(plan_steps, results):
    """
    If the last completed step was a query for an href to /papers/,
    automatically open it in a new tab. Returns a list of extra steps executed.
    """
    if not results: return []
    last = results[-1]
    if not last.get("ok"): return []
    data = (last.get("data") or {})
    arr = data.get("results") or []
    if not arr: return []

    href = arr[0]
    if not isinstance(href, str): return []

    # Build absolute URL if needed (assume HF base)
    if href.startswith("/"):
        base = "https://huggingface.co"
        url = urljoin(base, href)
    else:
        url = href

    # Synthesize and run an openTab
    return [{"id": "autotab", "cmd": "openTab", "args": {"url": url, "active": True}}]

async def wait_for_adapter(ws, timeout_sec=45):
    end = asyncio.get_event_loop().time() + timeout_sec
    while True:
        await ws.send(json.dumps({"type": "status"}))
        resp = json.loads(await ws.recv())
        if resp.get("type") == "status" and resp.get("adapter_connected"):
            return True
        if asyncio.get_event_loop().time() > end:
            return False
        await asyncio.sleep(0.25)

async def recv_by_id(ws, expected_id: str, timeout=30):
    end = asyncio.get_event_loop().time() + timeout
    while True:
        remaining = max(0.1, end - asyncio.get_event_loop().time())
        ws_msg = await asyncio.wait_for(ws.recv(), timeout=remaining)
        try:
            msg = json.loads(ws_msg)
        except:
            continue
        if not isinstance(msg, dict):
            continue
        if msg.get("id") != expected_id:
            log_event("controller_skip", {"raw": ws_msg})
            continue
        return msg

async def run_step(ws, step: Dict[str, Any], timeout=30):
    await ws.send(json.dumps(step))
    resp = await recv_by_id(ws, step["id"], timeout=timeout)
    log_event("controller_step", {"req": step, "resp": resp})
    return resp

async def run_plan(plan_steps: list[Dict[str, Any]]):
    async with websockets.connect(URI) as ws:
        await ws.send(json.dumps({"type": "hello", "role": "controller"}))
        _ = await ws.recv()

        if not await wait_for_adapter(ws, 45):
            return {"ok": False, "error": "adapter_not_connected",
                    "hint": "Load/refresh the Chrome extension (adapter) to connect to ws://127.0.0.1:8765"}

        results = []
        for step in plan_steps:
            resp = await run_step(ws, step)
            if not resp.get("ok"):
                return {"ok": False, "failed_step": step, "resp": resp, "results": results}
            results.append(resp)
            for step in _maybe_follow_href(plan_steps, results):
                ex_resp = await run_step(ws, step)
                results.append(ex_resp)
        return {"ok": True, "results": results}

