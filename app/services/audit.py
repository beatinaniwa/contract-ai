import os, json, hashlib, datetime

def _hash_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()

def save_audit_log(form_json, source_text: str, excel_path: str, out_dir: str = "outputs") -> str:
    os.makedirs(out_dir, exist_ok=True)
    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    record = {
        "timestamp": ts,
        "form": form_json,
        "source_text_hash": _hash_bytes(source_text.encode("utf-8")) if source_text else None,
        "excel_path": excel_path,
    }
    p = os.path.join(out_dir, f"audit_{ts}.json")
    with open(p, "w", encoding="utf-8") as f:
        json.dump(record, f, ensure_ascii=False, indent=2)
    return p
