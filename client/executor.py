import asyncio, json
import websockets
from typing import Dict, Any
from utils import log_event

URI = "ws://127.0.0.1:8765"

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
        # hello as controller
        await ws.send(json.dumps({"type": "hello", "role": "controller"}))
        _ = await ws.recv()
        assert await wait_for_adapter(ws, 45), "Adapter not connected; reload the extension."

        results = []
        for step in plan_steps:
            resp = await run_step(ws, step)
            if not resp.get("ok"):
                return {"ok": False, "failed_step": step, "resp": resp, "results": results}
            results.append(resp)
        return {"ok": True, "results": results}
