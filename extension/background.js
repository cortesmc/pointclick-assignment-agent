// MV3 background service worker — Point&Click Adapter
// Connects to ws://127.0.0.1:8765, declares role "adapter", and routes commands
// to the active tab's content script (DOM actions) or handles tab-level commands.

let ws;
let reconnectTimer;
const WS_URL = "ws://127.0.0.1:8765";
const RETRY_MS = 1500;

let activeTabId = null;

// --- WS helpers ---
function wsSend(obj) {
    if (ws && ws.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify(obj));
    } else {
        console.warn("[Adapter] WS not open; cannot send:", obj);
    }
}

function connectWS() {
    if (ws && (ws.readyState === WebSocket.OPEN || ws.readyState === WebSocket.CONNECTING)) return;

    console.log("[Adapter] Connecting to", WS_URL);
    ws = new WebSocket(WS_URL);

    ws.onopen = () => {
        console.log("[Adapter] WS connected.");
        wsSend({ type: "hello", role: "adapter" });
        // Optional handshake ping
        wsSend({ id: "boot-1", cmd: "ping" });
    };

    ws.onmessage = (evt) => {
        let msg;
        try {
            msg = JSON.parse(evt.data);
        } catch {
            console.warn("[Adapter] Invalid JSON from WS:", evt.data);
            return;
        }

        // Ignore non-command payloads (role acks, errors, plain responses)
        if (!msg || !msg.cmd) {
            console.log("[Adapter] (info) non-command message:", msg);
            return;
        }

        // Only route true controller commands
        handleControllerCommand(msg);
    };

    ws.onclose = () => {
        console.warn("[Adapter] WS closed; reconnecting in", RETRY_MS, "ms");
        if (reconnectTimer) clearTimeout(reconnectTimer);
        reconnectTimer = setTimeout(connectWS, RETRY_MS);
    };

    ws.onerror = (err) => {
        console.warn("[Adapter] WS error:", err);
        try { ws.close(); } catch { }
    };
}

// --- Tabs helpers ---

async function delay(ms) { return new Promise(r => setTimeout(r, ms)); }

async function ensureContentScript(tabId) {
    // Quick ping to check if the content script is ready
    try {
        const resp = await chrome.tabs.sendMessage(tabId, { type: "adapter:ping" });
        if (resp && resp.ok) return true;
    } catch (e) {
        // No receiver — we'll inject
    }

    // Programmatic injection (requires "scripting" permission)
    try {
        await chrome.scripting.executeScript({
            target: { tabId },
            files: ["contentScript.js"]
        });
    } catch (e) {
        console.warn("[Adapter] executeScript failed:", e);
        // If executeScript fails because CS is already there, continue anyway
    }

    // Give it a moment to initialize and register its onMessage listener
    await delay(150);
    return true;
}

async function getOrCreateActiveTab() {
    // Use the currently active tab in current window if available
    const tabs = await chrome.tabs.query({ active: true, currentWindow: true });
    if (tabs && tabs[0]) {
        activeTabId = tabs[0].id;
        return tabs[0].id;
    }
    // Fallback: create a new tab
    const created = await chrome.tabs.create({ url: "about:blank" });
    activeTabId = created.id;
    return activeTabId;
}

function waitForTabComplete(tabId, timeoutMs = 15000) {
    return new Promise((resolve, reject) => {
        const start = Date.now();
        function listener(id, info) {
            if (id === tabId && info.status === "complete") {
                chrome.tabs.onUpdated.removeListener(listener);
                resolve(true);
            }
        }
        chrome.tabs.onUpdated.addListener(listener);

        const t = setInterval(async () => {
            if (Date.now() - start > timeoutMs) {
                chrome.tabs.onUpdated.removeListener(listener);
                clearInterval(t);
                reject(new Error("tab_load_timeout"));
            }
        }, 250);
    });
}

// --- Command handling ---
async function handleControllerCommand(msg) {
    const { id, cmd, args = {} } = msg;
    try {
        if (cmd === "navigate") {
            const url = args.url;
            const tabId = await getOrCreateActiveTab();
            await chrome.tabs.update(tabId, { url });
            await waitForTabComplete(tabId, 20000);
            await ensureContentScript(tabId);

            wsSend({ id, ok: true, data: { tabId, url } });
            return;
        }

        // Commands that need DOM access → content script
        if (["waitFor", "query", "click", "type", "scroll"].includes(cmd)) {
            const tabId = activeTabId ?? (await getOrCreateActiveTab());

            await ensureContentScript(tabId);

            const resp = await chrome.tabs.sendMessage(tabId, { type: "adapter:cmd", id, cmd, args });
            wsSend(resp); // should be {id, ok, data? , error?}
            return;
        }

        if (cmd === "ping") {
            wsSend({ id, ok: true, data: "pong" });
            return;
        }

        wsSend({ id, ok: false, error: "unknown_command" });
    } catch (e) {
        wsSend({ id: msg.id, ok: false, error: String(e?.message || e) });
    }
}

// Keep activeTabId in sync as the user changes tabs
chrome.tabs.onActivated.addListener(({ tabId }) => { activeTabId = tabId; });

// Lifecycle
chrome.runtime.onInstalled.addListener(() => { console.log("[Adapter] Installed."); connectWS(); });
chrome.runtime.onStartup.addListener(() => { console.log("[Adapter] Startup."); connectWS(); });
connectWS();

// Receive replies from content script and forward them to the controller via WS
chrome.runtime.onMessage.addListener((msg, sender, _sendResponse) => {
    // Expecting messages like {id, ok, data?, error?}
    if (msg && (msg.ok === true || msg.ok === false) && msg.id) {
        wsSend(msg);
    }
});
