# Point&Click Assignment Agent — README

A tiny LLM→plan→execute agent that drives your browser through a Chrome extension.
Tested with OpenAI; Anthropic should work the same by setting the corresponding key.

---

## 1) What this does (quick)

* You write: “open hugging face papers and get the latest link about transformers”.
* The **LLM planner** returns a small JSON plan (open tab, wait, type, query).
* The **executor** runs the plan via a local **WebSocket relay** to a **Chrome MV3 extension**.
* The extension executes DOM actions in the active tab and reports results.

---

## 2) Architecture (fast map)

* `client/websocket_server.py` — local relay (WS) between client and extension.
* `client/orchestrator.py` — CLI entrypoint. Calls LLM → executes plan.
* `client/llm_planner.py` — prompts OpenAI/Anthropic and validates plan JSON.
* `client/executor.py` — sends steps over WS; handles responses; auto-opens links.
* `client/schema.py` — Pydantic models for `Plan` and `Command`.
* `client/utils.py` — JSONL logger (`runlog.jsonl`).

**Chrome extension**

* `extension/background.js` — connects to WS, handles tab commands, injects content script.
* `extension/contentScript.js` — DOM actions: waitFor, query, click, type, scroll.
* `extension/manifest.json` — MV3 manifest with required permissions.

**Not necessary for main LLM execution**

* Demo/test helpers (e.g., `demo_type_scroll_wiki.py`, `test_controller.py`).
* Rule-based planner (`planner.py`) if you’re using LLM-only.

---

## 3) Prerequisites

* Python 3.10+
* Chrome or Chromium-based browser
* An OpenAI API key (tested). Anthropic key is optional and supported.

---

## 4) Install (Windows-friendly)

From the `client` folder:

```bash
# Create and activate a venv (PowerShell)
python -m venv .venv
.venv\Scripts\Activate.ps1

# Or CMD
# .venv\Scripts\activate.bat

# Install deps
pip install websockets python-dotenv pydantic openai anthropic
```

Create a `.env` file in `client/`:

```
OPENAI_API_KEY=sk-your-openai-key
# Optional for Anthropic:
# ANTHROPIC_API_KEY=sk-ant-your-anthropic-key
# Defaults (can be overridden on CLI)
OPENAI_MODEL=gpt-4o-mini
ANTHROPIC_MODEL=claude-3-5-sonnet-latest
```

---

## 5) Load the Chrome extension

1. Open `chrome://extensions`
2. Enable **Developer mode**
3. Click **Load unpacked** and select the `extension/` directory
4. Click **Reload** on the extension.
5. In the Service Worker console, you should see it connect once the WS server is running.

Permissions used: `tabs`, `scripting`, `activeTab`, `alarms`, `webNavigation`.

---

## 6) Run

### Step A — Start the relay server

From `client/`:

```bash
python websocket_server.py
```

You should see:

```
{"event": "server_listening", "data": {"host": "127.0.0.1", "port": 8765}}
```

### Step B — Run the orchestrator in a second terminal

From `client/` (PowerShell or CMD):

```bash
# Example: Hugging Face search (OpenAI)
python orchestrator.py --provider openai --model gpt-4o-mini "open hugging face papers and get the latest link about transformers"
```

If you want Anthropic:

```bash
python orchestrator.py --provider anthropic --model claude-3-5-sonnet-latest "open hugging face papers and get the latest link about transformers"
```

---

## 7) CLI usage

```
python orchestrator.py [-h] [--provider {openai,anthropic}] [--model MODEL] [--raw] [--silent] "task"
```

* `--provider` — `openai` (tested) or `anthropic`
* `--model` — e.g. `gpt-4o-mini` or `claude-3-5-sonnet-latest`
* `--raw` — print only raw JSON result
* `--silent` — execute with no console output

### Examples

Hugging Face, generic:

```bash
python orchestrator.py --provider openai --model gpt-4o-mini "open hugging face papers and get the latest link about transformers"
```

Hugging Face, “grok”:

```bash
python orchestrator.py --provider openai --model gpt-4o-mini "search for the last paper about grok on hugging face"
```

Gmail promotions, no timeframe:

```bash
python orchestrator.py --provider openai --model gpt-4o-mini "open gmail promotions and list unread promotions"
```

Gmail promotions, last week:

```bash
python orchestrator.py --provider openai --model gpt-4o-mini "open gmail promotions and list unread promotions of the last week"
```

Ping test (connectivity sanity):

```bash
python orchestrator.py --provider openai --model gpt-4o-mini "ping"
```

Windows tip: don’t use `\` for line continuation; always put the task in quotes on the same line.

---

## 8) How it plans (LLM rules)

* Allowed commands: `openTab`, `navigate`, `waitFor`, `query`, `click`, `type`, `scroll`, `switchTab`, `screenshot`, `ping`.
* The planner is instructed **not** to add date/time filters unless you ask (e.g., Gmail `newer_than:14d` only when requested).
* Few-shots teach how to search on Hugging Face and how to form Gmail queries.

---

## 9) Logs

`client/runlog.jsonl` contains a JSON line per event:

* server starts/stops
* adapter/controller connects
* each executed step and response
* any errors returned by the extension

This is the fastest way to debug.

---

## 10) Troubleshooting

* `adapter_not_connected`:
  Start `websocket_server.py` first, then reload the extension (`chrome://extensions` → Reload).
  Clicking the extension icon also triggers a reconnect.

* Nothing types or clicks:
  Check the Service Worker console; ensure the content script is injected (background logs injection).
  Some pages need a short delay; the code already waits for selectors with timeouts.

* Gmail rows time out:
  It can mean empty results. The plan usually queries after waiting; empty is OK. Use time filters if needed.

* Firewall prompts:
  Allow local loopback for Python on port 8765.

---

## 11) Extending with new functions (optional)

Pattern:

1. Add a new command name to `schema.py` (e.g., `calendarSearch`).
2. Allow it in `llm_planner.py` and add 1–2 few-shot examples.
3. Implement it in `executor.py` (call an API) and return JSON.
   No changes needed in the Chrome extension if the tool doesn’t touch the DOM.

This keeps browser automation and API tools cleanly separated.

---

## 12) Minimal file list to keep

* `client/`

  * `websocket_server.py`
  * `orchestrator.py`
  * `llm_planner.py`
  * `executor.py`
  * `schema.py`
  * `utils.py`
  * `.env` (your keys)
* `extension/`

  * `background.js`
  * `contentScript.js`
  * `manifest.json`

You can remove demos/tests and any rule-based planner files if present.

---

## 13) License/Notes

This is a minimal teaching/reference project. Use at your own risk.
Be mindful when automating websites; respect terms of service.
