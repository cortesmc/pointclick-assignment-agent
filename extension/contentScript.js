// Content script: executes DOM-level commands on behalf of the background worker.

const log = (...a) => console.log("[ContentScript]", ...a);

async function waitForSelector(selector, timeoutMs = 10000) {
    const start = Date.now();
    // Immediate check
    if (selector && document.querySelector(selector)) return true;

    return new Promise((resolve, reject) => {
        const observer = new MutationObserver(() => {
            if (document.querySelector(selector)) {
                observer.disconnect();
                resolve(true);
            }
            if (Date.now() - start > timeoutMs) {
                observer.disconnect();
                reject(new Error("waitFor_timeout"));
            }
        });
        observer.observe(document.documentElement || document.body, { childList: true, subtree: true });

        // Fallback timer in case there are no mutations
        const interval = setInterval(() => {
            if (document.querySelector(selector)) {
                clearInterval(interval);
                observer.disconnect();
                resolve(true);
            }
            if (Date.now() - start > timeoutMs) {
                clearInterval(interval);
                observer.disconnect();
                reject(new Error("waitFor_timeout"));
            }
        }, 150);
    });
}

function selectOne(selector) {
    return document.querySelector(selector);
}
function selectAll(selector) {
    return Array.from(document.querySelectorAll(selector));
}

function safeClick(el) {
    if (!el) throw new Error("element_not_found");
    el.scrollIntoView({ block: "center", inline: "center" });
    el.dispatchEvent(new MouseEvent("mouseover", { bubbles: true }));
    el.click();
    return true;
}

function typeText(el, text, submit) {
    if (!el) throw new Error("element_not_found");
    el.focus();
    el.value = text;
    el.dispatchEvent(new Event("input", { bubbles: true }));
    el.dispatchEvent(new Event("change", { bubbles: true }));
    if (submit) {
        // Try form submit if inside a form
        const form = el.form;
        if (form) form.submit();
        else el.dispatchEvent(new KeyboardEvent("keydown", { key: "Enter", bubbles: true }));
    }
    return true;
}

chrome.runtime.onMessage.addListener((msg, _sender, _sendResponse) => {
    (async () => {
        if (msg?.type !== "adapter:cmd") return;
        const { id, cmd, args = {} } = msg;
        try {
            if (cmd === "waitFor") {
                await waitForSelector(args.selector, args.timeoutMs || 10000);
                chrome.runtime.sendMessage({ id, ok: true, data: { waitedFor: args.selector } });
                return;
            }

            if (cmd === "query") {
                const { selector, all = false, attr = null, limit = null } = args;
                if (!selector) throw new Error("missing_selector");
                const nodes = all ? selectAll(selector) : [selectOne(selector)].filter(Boolean);
                let out;
                if (attr) out = nodes.map(n => n?.getAttribute(attr) ?? null);
                else out = nodes.map(n => (n?.innerText ?? "").trim());
                if (limit && Number.isInteger(limit)) out = out.slice(0, limit);
                chrome.runtime.sendMessage({ id, ok: true, data: { results: out } });
                return;
            }

            if (cmd === "click") {
                const { selector, xy } = args;
                if (selector) {
                    const el = selectOne(selector);
                    safeClick(el);
                    chrome.runtime.sendMessage({ id, ok: true, data: { clicked: selector } });
                    return;
                } else if (xy) {
                    const el = document.elementFromPoint(xy.x, xy.y);
                    safeClick(el);
                    chrome.runtime.sendMessage({ id, ok: true, data: { clickedXY: xy } });
                    return;
                } else {
                    throw new Error("missing_selector_or_xy");
                }
            }

            if (cmd === "type") {
                const { selector, text, submit } = args;
                const el = selectOne(selector);
                typeText(el, text, submit);
                chrome.runtime.sendMessage({ id, ok: true, data: { typed: text?.length || 0 } });
                return;
            }

            if (cmd === "scroll") {
                const { to, selector } = args;
                if (selector) {
                    const el = selectOne(selector);
                    if (!el) throw new Error("element_not_found");
                    el.scrollIntoView({ behavior: "smooth", block: "center" });
                } else if (to === "top") window.scrollTo({ top: 0, behavior: "smooth" });
                else if (to === "bottom") window.scrollTo({ top: document.body.scrollHeight, behavior: "smooth" });
                chrome.runtime.sendMessage({ id, ok: true, data: { scrolled: true } });
                return;
            }

            chrome.runtime.sendMessage({ id, ok: false, error: "unknown_command" });
        } catch (e) {
            chrome.runtime.sendMessage({ id, ok: false, error: String(e?.message || e) });
        }
    })();

    // We respond asynchronously via chrome.runtime.sendMessage back to background
    // so return true would be for sendResponse path; we don't use it here.
});

chrome.runtime.onMessage.addListener((msg, _sender, _sendResponse) => {
    if (msg?.type === "adapter:ping") {
        chrome.runtime.sendMessage({ ok: true, type: "adapter:pong" });
    }
});

