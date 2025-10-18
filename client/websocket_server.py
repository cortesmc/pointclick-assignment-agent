import asyncio
import json
import websockets
from websockets.server import WebSocketServerProtocol
from utils import log_event

HOST = "127.0.0.1"
PORT = 8765

ADAPTER_WS: WebSocketServerProtocol | None = None
CONTROLLER_WS: WebSocketServerProtocol | None = None
CLIENT_ROLES = {}  # ws -> "adapter" | "controller"

async def safe_send(ws: WebSocketServerProtocol | None, payload: dict):
    if ws is None:
        return False
    try:
        await ws.send(json.dumps(payload))
        return True
    except Exception as e:
        log_event("send_error", {"error": repr(e)})
        return False

async def broadcast_to_controllers(payload: dict):
    # single controller in this assignment, but keep it generic
    for ws, role in list(CLIENT_ROLES.items()):
        if role == "controller":
            await safe_send(ws, payload)

def status_payload():
    return {
        "type": "status",
        "adapter_connected": ADAPTER_WS is not None,
        "controller_connected": CONTROLLER_WS is not None,
    }

async def handle_message(ws: WebSocketServerProtocol, raw: str):
    global ADAPTER_WS, CONTROLLER_WS
    try:
        msg = json.loads(raw)
    except json.JSONDecodeError:
        log_event("recv_invalid_json", {"raw": raw})
        await safe_send(ws, {"ok": False, "error": "invalid_json"})
        return

    log_event("recv", msg)

    # Role negotiation
    if msg.get("type") == "hello" and msg.get("role") in ("adapter", "controller"):
        role = msg["role"]
        CLIENT_ROLES[ws] = role
        if role == "adapter":
            ADAPTER_WS = ws
        else:
            CONTROLLER_WS = ws
        await safe_send(ws, {"ok": True, "role": role})
        log_event("role_set", {"role": role})
        # Notify any controllers that adapter/controller status changed
        await broadcast_to_controllers(status_payload())
        return

    # Controller can ask for status at any time
    if msg.get("type") == "status":
        await safe_send(ws, status_payload())
        return

    # Ping handler for either side
    if msg.get("cmd") == "ping":
        await safe_send(ws, {"id": msg.get("id"), "ok": True, "data": "pong"})
        return

    # Routing rules
    role = CLIENT_ROLES.get(ws)
    if role == "controller":
        target = ADAPTER_WS
    elif role == "adapter":
        target = CONTROLLER_WS
    else:
        await safe_send(ws, {"id": msg.get("id"), "ok": False, "error": "role_not_set"})
        return

    if target is None:
        await safe_send(ws, {"id": msg.get("id"), "ok": False, "error": "peer_not_connected"})
        return

    ok = await safe_send(target, msg)
    if not ok:
        await safe_send(ws, {"id": msg.get("id"), "ok": False, "error": "forward_failed"})

async def handler(ws: WebSocketServerProtocol):
    log_event("client_connected", {"remote": str(ws.remote_address)})
    try:
        async for raw in ws:
            await handle_message(ws, raw)
    except Exception as e:
        log_event("client_error", {"error": repr(e)})
    finally:
        role = CLIENT_ROLES.pop(ws, None)
        global ADAPTER_WS, CONTROLLER_WS
        if role == "adapter" and ADAPTER_WS is ws:
            ADAPTER_WS = None
        if role == "controller" and CONTROLLER_WS is ws:
            CONTROLLER_WS = None
        log_event("client_disconnected", {"remote": str(ws.remote_address), "role": role})
        # Notify controllers that status changed
        await broadcast_to_controllers(status_payload())

async def main():
    log_event("server_starting", {"host": HOST, "port": PORT})
    async with websockets.serve(handler, HOST, PORT):
        log_event("server_listening", {"host": HOST, "port": PORT})
        await asyncio.Future()

if __name__ == "__main__":
    asyncio.run(main())
