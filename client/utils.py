import json, time, os

RUNLOG = os.path.join(os.path.dirname(__file__), "runlog.jsonl")

def log_event(event_type: str, data: dict):
    rec = {
        "t": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime()),
        "event": event_type,
        "data": data,
    }
    with open(RUNLOG, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
