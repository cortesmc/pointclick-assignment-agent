import asyncio
import json
import websockets
from utils import log_event

URI = "ws://127.0.0.1:8765"

async def wait_for_adapter(ws, timeout_sec=10):
    end = asyncio.get_event_loop().time() + timeout_sec
    while True:
        await ws.send(json.dumps({"type": "status"}))
        resp = json.loads(await ws.recv())
        if resp.get("type") == "status" and resp.get("adapter_connected"):
            return True
        if asyncio.get_event_loop().time() > end:
            return False
        await asyncio.sleep(0.3)

async def recv_by_id(ws, expected_id, timeout=20):
    """Read messages until we get one with id == expected_id."""
    end = asyncio.get_event_loop().time() + timeout
    while True:
        remaining = max(0.1, end - asyncio.get_event_loop().time())
        ws_msg = await asyncio.wait_for(ws.recv(), timeout=remaining)
        try:
            msg = json.loads(ws_msg)
        except:
            continue
        # Ignore status/info
        if not isinstance(msg, dict):
            continue
        if msg.get("id") != expected_id:
            # Not our turn; you could buffer/log it if desired
            log_event("controller_skip", {"raw": ws_msg})
            continue
        return msg

async def main():
    async with websockets.connect(URI) as ws:
        await ws.send(json.dumps({"type": "hello", "role": "controller"}))
        print("hello/role → controller ack:", await ws.recv())

        ready = await wait_for_adapter(ws, timeout_sec=15)
        print("adapter ready:", ready)
        if not ready:
            print("Adapter not connected. Open Chrome and reload the extension.")
            return

        steps = [
            {"id": "1", "cmd": "navigate", "args": {"url": "https://huggingface.co/papers"}},
            {"id": "2", "cmd": "waitFor", "args": {"selector": "main section article", "timeoutMs": 10000}},
            {"id": "3", "cmd": "query", "args": {"selector": "main section article:nth-of-type(1) a[href^='/papers/']", "all": False, "attr": "href"}},
        ]


        for step in steps:
            print("→", step)
            await ws.send(json.dumps(step))
            resp = await recv_by_id(ws, step["id"], timeout=30)
            print("←", resp)
            log_event("controller_recv", {"raw": json.dumps(resp)})

            if not resp.get("ok", False):
                print("Step failed; aborting.")
                return

if __name__ == "__main__":
    asyncio.run(main())
