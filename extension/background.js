// MV3 background service worker: connects to ws://127.0.0.1:8765 as "adapter"
// and routes commands to the active tab's content script (DOM actions).
// Tab-level commands (openTab, navigate, screenshot) are handled here.

let ws, reconnectTimer;
const WS_URL = "ws://127.0.0.1:8765";
const RETRY_MS = 1500;
const actionTypes = ["waitFor", "query", "click", "type", "scroll", "switchTab"];
let activeTabId = null;

function wsSend(obj) {
  if (ws && ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify(obj));
  else console.warn("[Adapter] WS not open; cannot send:", obj);
}

function connectWS() {
  if (ws && (ws.readyState === WebSocket.OPEN || ws.readyState === WebSocket.CONNECTING)) return;
  console.log("[Adapter] Connecting to", WS_URL);
  ws = new WebSocket(WS_URL);

  ws.onopen = () => {
    console.log("[Adapter] WS connected.");
    wsSend({ type: "hello", role: "adapter" });
    wsSend({ id: "boot-1", cmd: "ping" });
  };

  ws.onmessage = (evt) => {
    let msg;
    try { msg = JSON.parse(evt.data); } catch { return; }
    if (!msg || !msg.cmd) return;
    handleControllerCommand(msg);
  };

  ws.onclose = () => {
    if (reconnectTimer) clearTimeout(reconnectTimer);
    reconnectTimer = setTimeout(connectWS, RETRY_MS);
  };

  ws.onerror = () => { try { ws.close(); } catch {} };
}

async function delay(ms){ return new Promise(r => setTimeout(r, ms)); }

async function ensureContentScript(tabId) {
  try {
    const pong = await chrome.tabs.sendMessage(tabId, { type: "adapter:ping" });
    if (pong && pong.ok) return true;
  } catch {}
  try {
    await chrome.scripting.executeScript({ target: { tabId }, files: ["contentScript.js"] });
  } catch (e) {
    console.warn("[Adapter] inject CS error:", e);
  }
  await delay(150);
  return true;
}

async function sendToContentWithRetry(tabId, payload, attempts = 2) {
  for (let i = 0; i < attempts; i++) {
    try { return await chrome.tabs.sendMessage(tabId, payload); }
    catch (e) {
      if (String(e?.message || e).includes("Receiving end does not exist")) {
        await ensureContentScript(tabId); await delay(150); continue;
      }
      throw e;
    }
  }
  throw new Error("no_receiver_after_retry");
}

async function getOrCreateActiveTab() {
  const tabs = await chrome.tabs.query({ active: true, currentWindow: true });
  if (tabs && tabs[0]) { activeTabId = tabs[0].id; return tabs[0].id; }
  const created = await chrome.tabs.create({ url: "about:blank" });
  activeTabId = created.id; return activeTabId;
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

async function handleControllerCommand(msg) {
  const { id, cmd, args = {} } = msg;
  try {
    if (cmd === "navigate") {
      const tabId = await getOrCreateActiveTab();
      await chrome.tabs.update(tabId, { url: args.url });
      await waitForTabComplete(tabId, 20000);
      await ensureContentScript(tabId);
      wsSend({ id, ok: true, data: { tabId, url: args.url } });
      return;
    }

    if (actionTypes.includes(cmd)) {
      const tabId = activeTabId ?? (await getOrCreateActiveTab());
      await ensureContentScript(tabId);
      let resp;
      try { resp = await sendToContentWithRetry(tabId, { type: "adapter:cmd", id, cmd, args }, 2); }
      catch (e) { wsSend({ id, ok: false, error: String(e?.message || e) }); return; }
      if (resp !== undefined) wsSend(resp);  // CS may also reply via runtime.sendMessage
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

    if (cmd === "ping") { wsSend({ id, ok: true, data: "pong" }); return; }
    wsSend({ id, ok: false, error: "unknown_command" });
  } catch (e) {
    wsSend({ id: msg.id, ok: false, error: String(e?.message || e) });
  }
}

chrome.tabs.onActivated.addListener(({ tabId }) => { activeTabId = tabId; });

function boot(){ console.log("[Adapter] Boot."); connectWS(); }
function setupAlarms(){ chrome.alarms.create("pc_keepalive", { periodInMinutes: 4 }); }
chrome.runtime.onInstalled.addListener(boot);
chrome.runtime.onStartup.addListener(boot);
chrome.runtime.onInstalled.addListener(setupAlarms);
chrome.runtime.onStartup.addListener(setupAlarms);
chrome.alarms.onAlarm.addListener((a) => { if (a.name === "pc_keepalive") connectWS(); });
chrome.webNavigation.onCommitted.addListener(() => connectWS());
chrome.tabs.onActivated.addListener(() => connectWS());
chrome.action.onClicked.addListener(() => connectWS());
chrome.runtime.onMessage.addListener((msg) => { if (msg && (msg.ok === true || msg.ok === false) && msg.id) wsSend(msg); });
connectWS();
