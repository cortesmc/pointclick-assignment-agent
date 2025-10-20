// Content script: executes DOM-level commands (no tabs/screenshot here)

const log = (...a) => console.log("[ContentScript]", ...a);

async function waitForSelector(selector, timeoutMs = 10000) {
  const start = Date.now();
  if (selector && document.querySelector(selector)) return true;

  return new Promise((resolve, reject) => {
    const observer = new MutationObserver(() => {
      if (document.querySelector(selector)) {
        observer.disconnect();
        resolve(true);
      }
    });
    observer.observe(document.documentElement || document.body, { childList: true, subtree: true });

    const poll = setInterval(() => {
      if (document.querySelector(selector)) {
        clearInterval(poll);
        observer.disconnect();
        resolve(true);
      }
      if (Date.now() - start > timeoutMs) {
        clearInterval(poll);
        observer.disconnect();
        reject(new Error("waitFor_timeout"));
      }
    }, 150);
  });
}

const $ = (sel) => document.querySelector(sel);
const $$ = (sel) => Array.from(document.querySelectorAll(sel));

function safeClick(el) {
  if (!el) throw new Error("element_not_found");
  el.scrollIntoView({ block: "center", inline: "center" });
  el.dispatchEvent(new MouseEvent("mouseover", { bubbles: true }));
  el.click();
}

function typeText(el, text, submit) {
  if (!el) throw new Error("element_not_found");
  el.focus();
  el.value = text ?? "";
  el.dispatchEvent(new Event("input", { bubbles: true }));
  el.dispatchEvent(new Event("change", { bubbles: true }));
  if (submit) {
    const form = el.form;
    if (form) form.submit();
    else el.dispatchEvent(new KeyboardEvent("keydown", { key: "Enter", bubbles: true }));
  }
}

chrome.runtime.onMessage.addListener((msg, _sender, sendResponse) => {
  // quick ping from background to check CS presence
  if (msg?.type === "adapter:ping") {
    sendResponse({ ok: true, type: "adapter:pong" });
    return; // sync response
  }

  if (msg?.type !== "adapter:cmd") return;

  const { id, cmd, args = {} } = msg;

  (async () => {
    try {
      if (cmd === "waitFor") {
        await waitForSelector(args.selector, args.timeoutMs || 10000);
        sendResponse({ id, ok: true, data: { waitedFor: args.selector } });
        return;
      }

      if (cmd === "query") {
        const { selector, all = false, attr = null, limit = null } = args;
        if (!selector) throw new Error("missing_selector");
        const nodes = all ? $$(selector) : [$(selector)].filter(Boolean);
        let out = attr ? nodes.map(n => n?.getAttribute(attr) ?? null)
                       : nodes.map(n => (n?.innerText ?? "").trim());
        if (Number.isInteger(limit)) out = out.slice(0, limit);
        sendResponse({ id, ok: true, data: { results: out } });
        return;
      }

      if (cmd === "click") {
        const { selector, xy } = args;
        if (selector) {
          safeClick($(selector));
          sendResponse({ id, ok: true, data: { clicked: selector } });
          return;
        }
        if (xy) {
          const el = document.elementFromPoint(xy.x, xy.y);
          safeClick(el);
          sendResponse({ id, ok: true, data: { clickedXY: xy } });
          return;
        }
        throw new Error("missing_selector_or_xy");
      }

      if (cmd === "type") {
        const { selector, text, submit } = args;
        typeText($(selector), text, submit);
        sendResponse({ id, ok: true, data: { typed: (text || "").length } });
        return;
      }

      if (cmd === "scroll") {
        const { to, selector } = args;
        if (selector) {
          const el = $(selector);
          if (!el) throw new Error("element_not_found");
          el.scrollIntoView({ behavior: "smooth", block: "center" });
        } else if (to === "top") {
          window.scrollTo({ top: 0, behavior: "smooth" });
        } else if (to === "bottom") {
          window.scrollTo({ top: document.body.scrollHeight, behavior: "smooth" });
        }
        sendResponse({ id, ok: true, data: { scrolled: true } });
        return;
      }

      // Unknown command for CS
      sendResponse({ id, ok: false, error: "unknown_command" });
    } catch (e) {
      sendResponse({ id, ok: false, error: String(e?.message || e) });
    }
  })();

  // async response
  return true;
});
