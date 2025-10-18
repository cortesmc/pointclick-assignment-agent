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

async def step(ws, payload, timeout=30):
    await ws.send(json.dumps(payload))
    resp = await recv_by_id(ws, payload["id"], timeout=timeout)
    print("←", resp)
    log_event("controller_step", {"req": payload, "resp": resp})
    if not resp.get("ok", False):
        raise RuntimeError(f"Step failed: {resp}")
    return resp

async def main():
    async with websockets.connect(URI) as ws:
        # Identify as controller and wait for adapter
        await ws.send(json.dumps({"type": "hello", "role": "controller"}))
        _ = await ws.recv()
        assert await wait_for_adapter(ws, 15), "Adapter not connected; reload the extension."

        # 1) Go to Wikipedia Search
        print("→ navigate Wikipedia Search")
        await step(ws, {"id":"1", "cmd":"navigate", "args":{"url":"https://en.wikipedia.org/wiki/Special:Search"}})

        # 2) Wait for search input to appear
        print("→ waitFor #searchInput")
        await step(ws, {"id":"2", "cmd":"waitFor", "args":{"selector":"#searchInput", "timeoutMs":15000}})

        # 3) TYPE: enter query and submit
        print("→ type query + submit")
        await step(ws, {"id":"3", "cmd":"type", "args":{"selector":"#searchInput", "text":"UI Agents", "submit":True}})

        # 4) Wait for results container
        print("→ waitFor results")
        # results can be list or direct page; wait for main content area
        await step(ws, {"id":"4", "cmd":"waitFor", "args":{"selector":"#mw-content-text", "timeoutMs":15000}})

        # 5) SCROLL: to bottom then back to top
        print("→ scroll bottom")
        await step(ws, {"id":"5", "cmd":"scroll", "args":{"to":"bottom"}})
        print("→ scroll top")
        await step(ws, {"id":"6", "cmd":"scroll", "args":{"to":"top"}})

        # 6) QUERY: first search result (if we’re on results page)
        # try the common selector for search results
        print("→ query first result")
        q1 = {"id":"7", "cmd":"query", "args":{"selector":"div.mw-search-result-heading a", "all":False}}
        r1 = await step(ws, q1)
        titles = r1["data"]["results"]
        title = titles[0] if titles else None

        q2 = {"id":"8", "cmd":"query", "args":{"selector":"div.mw-search-result-heading a", "all":False, "attr":"href"}}
        r2 = await step(ws, q2)
        hrefs = r2["data"]["results"]
        href = hrefs[0] if hrefs else None
        url = f"https://en.wikipedia.org{href}" if href and href.startswith("/") else href

        print(json.dumps({"first_result": {"title": title, "url": url}}, ensure_ascii=False, indent=2))
        log_event("wiki_demo_done", {"title": title, "url": url})

if __name__ == "__main__":
    asyncio.run(main())
