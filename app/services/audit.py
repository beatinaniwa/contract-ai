import os
import json
import hashlib
import datetime


def _json_default(value):
    """Serialize datetimes to ISO strings for audit readability."""
    if isinstance(value, (datetime.date, datetime.datetime)):
        return value.isoformat()
    raise TypeError(f"Object of type {value.__class__.__name__} is not JSON serializable")

def _hash_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()

def save_audit_log(form_json, source_text: str, output_path: str, out_dir: str = "outputs") -> str:
    os.makedirs(out_dir, exist_ok=True)
    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    record = {
        "timestamp": ts,
        "form": form_json,
        "source_text_hash": _hash_bytes(source_text.encode("utf-8")) if source_text else None,
        "output_path": output_path,
    }
    p = os.path.join(out_dir, f"audit_{ts}.json")
    with open(p, "w", encoding="utf-8") as f:
        json.dump(record, f, ensure_ascii=False, indent=2, default=_json_default)
    return p
