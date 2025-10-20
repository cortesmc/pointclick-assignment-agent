// MV3 background service worker — Point&Click Adapter
// Connects to ws://127.0.0.1:8765, declares role "adapter", and routes commands
// to the active tab's content script (DOM actions) or handles tab-level commands.

let ws;
let reconnectTimer;
const WS_URL = "ws://127.0.0.1:8765";
const RETRY_MS = 1500;

// Commands that require DOM access → handled by content script
const actionTypes = ["waitFor", "query", "click", "type", "scroll", "switchTab"];

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
    // Ignore non-command payloads (role acks, status, plain responses)
    if (!msg || !msg.cmd) {
      console.log("[Adapter] (info) non-command message:", msg);
      return;
    }
    handleControllerCommand(msg);
  };

  ws.onclose = () => {
    console.warn("[Adapter] WS closed; reconnecting in", RETRY_MS, "ms");
    if (reconnectTimer) clearTimeout(reconnectTimer);
    reconnectTimer = setTimeout(connectWS, RETRY_MS);
  };

  ws.onerror = (err) => {
    console.warn("[Adapter] WS error:", err);
    try { ws.close(); } catch {}
  };
}

// --- Tabs helpers ---
async function delay(ms) { return new Promise(r => setTimeout(r, ms)); }

async function ensureContentScript(tabId) {
  try {
    const pong = await chrome.tabs.sendMessage(tabId, { type: "adapter:ping" });
    if (pong && pong.ok) return true;
  } catch (_) {
    // no receiver yet
  }
  try {
    await chrome.scripting.executeScript({ target: { tabId }, files: ["contentScript.js"] });
  } catch (e) {
    console.warn("[Adapter] executeScript (inject CS) error:", e);
  }
  await delay(150);
  return true;
}

async function sendToContentWithRetry(tabId, payload, attempts = 2) {
  for (let i = 0; i < attempts; i++) {
    try {
      const resp = await chrome.tabs.sendMessage(tabId, payload);
      return resp; // may be undefined if CS forwards asynchronously via runtime.sendMessage
    } catch (e) {
      if (String(e?.message || e).includes("Receiving end does not exist")) {
        await ensureContentScript(tabId);
        await delay(150);
        continue;
      }
      throw e;
    }
  }
  throw new Error("no_receiver_after_retry");
}

async function getOrCreateActiveTab() {
  const tabs = await chrome.tabs.query({ active: true, currentWindow: true });
  if (tabs && tabs[0]) {
    activeTabId = tabs[0].id;
    return tabs[0].id;
  }
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
        clearInterval(t);
        resolve(true);
      }
    }
    chrome.tabs.onUpdated.addListener(listener);

    const t = setInterval(() => {
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
    if (actionTypes.includes(cmd)) {
      const tabId = activeTabId ?? (await getOrCreateActiveTab());
      await ensureContentScript(tabId);

      let resp;
      try {
        resp = await sendToContentWithRetry(tabId, { type: "adapter:cmd", id, cmd, args }, 2);
      } catch (e) {
        wsSend({ id, ok: false, error: String(e?.message || e) });
        return;
      }
      if (resp !== undefined) {
        wsSend(resp);
      }
      return;
    }

    if (cmd === "switchTab") {
      const { index, title, urlMatch } = args;
      const tabs = await chrome.tabs.query({});
      let target = null;

      if (Number.isInteger(index) && tabs[index]) target = tabs[index];
      if (!target && title) target = tabs.find(t => (t.title || "").includes(title));
      if (!target && urlMatch) target = tabs.find(t => (t.url || "").includes(urlMatch));

      if (!target) { wsSend({ id, ok: false, error: "tab_not_found" }); return; }

      await chrome.tabs.update(target.id, { active: true });
      activeTabId = target.id;
      wsSend({ id, ok: true, data: { tabId: target.id, title: target.title, url: target.url } });
      return;
    }

    if (cmd === "screenshot") {
      const tabId = activeTabId ?? (await getOrCreateActiveTab());
      const { format = "png" } = args || {};
      try {
        const dataUrl = await chrome.tabs.captureVisibleTab(undefined, { format });
        wsSend({ id, ok: true, data: { dataUrl } });
      } catch (e) {
        wsSend({ id, ok: false, error: String(e?.message || e) });
      }
      return;
    }

    if (cmd === "openTab") {
      const { url, active = true } = args || {};
      if (!url) { wsSend({ id, ok: false, error: "missing_url" }); return; }
      try {
        const tab = await chrome.tabs.create({ url, active });
        activeTabId = tab.id;
        wsSend({ id, ok: true, data: { tabId: tab.id, url: tab.url } });
      } catch (e) {
        wsSend({ id, ok: false, error: String(e?.message || e) });
      }
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

// Track currently active tab
chrome.tabs.onActivated.addListener(({ tabId }) => { activeTabId = tabId; });

// ---- Lifecycle / keepalive ----
function boot() { console.log("[Adapter] Boot."); connectWS(); }
function setupAlarms() { chrome.alarms.create("pc_keepalive", { periodInMinutes: 4 }); }

chrome.runtime.onInstalled.addListener(boot);
chrome.runtime.onStartup.addListener(boot);
chrome.runtime.onInstalled.addListener(setupAlarms);
chrome.runtime.onStartup.addListener(setupAlarms);

chrome.alarms.onAlarm.addListener((a) => {
  if (a.name === "pc_keepalive") connectWS();
});

// Also reconnect on common lifecycle events
chrome.webNavigation.onCommitted.addListener(() => connectWS());
chrome.tabs.onActivated.addListener(() => connectWS());

// Clicking the extension icon forces a connect (handy in dev)
chrome.action.onClicked.addListener(() => connectWS());

// Receive replies from content script and forward them to the controller via WS
chrome.runtime.onMessage.addListener((msg, sender, _sendResponse) => {
  // Expecting messages like {id, ok, data?, error?}
  if (msg && (msg.ok === true || msg.ok === false) && msg.id) {
    wsSend(msg);
  }
});

// Initial connect
connectWS();
