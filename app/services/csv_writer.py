from __future__ import annotations

import csv
import datetime as _dt
import os
from typing import Any, Dict, List

import yaml


def _fmt_date(value: Any) -> str:
    if value is None:
        return ""
    # Accept date/datetime or preformatted string
    try:
        # date or datetime
        return value.strftime("%Y-%m-%d")  # type: ignore[call-arg]
    except Exception:
        return str(value)


def _init_row(headers: List[str]) -> Dict[str, Any]:
    row: Dict[str, Any] = {}
    for h in headers:
        row[h] = ""
    return row


def _format_list_value(values: Any) -> str:
    """Join list-like values with '、'. Convert non-lists to str.

    Examples:
      ["要求仕様", "図面"] -> "要求仕様、図面"
    """
    if values is None:
        return ""
    if isinstance(values, (list, tuple)):
        return "、".join(str(v) for v in values if str(v).strip())
    return str(values)


def write_csv(form_data: Dict[str, Any], mapping_yaml_path: str, out_dir: str = "outputs") -> str:
    """Write a single-row CSV using utf-8-sig BOM.

    The mapping YAML defines column headers and how fields map into columns.
    """
    with open(mapping_yaml_path, "r", encoding="utf-8") as f_yaml:
        cfg = yaml.safe_load(f_yaml) or {}

    headers: List[str] = list(cfg.get("headers", []))
    if not headers:
        raise ValueError("csv_mapping.yaml に headers が定義されていません。")

    row = _init_row(headers)

    # 1) Direct field -> header mapping
    fields_map: Dict[str, str] = cfg.get("fields", {})
    for field, header in fields_map.items():
        value = form_data.get(field)
        if value is None:
            continue
        if field.endswith("_date") or field in {"request_date", "desired_due_date", "received_date"}:
            row[header] = _fmt_date(value)
        elif field in {"info_from_us", "info_from_them"}:
            # Join selected options only; free-text 'その他' is handled in separate columns
            values: List[str] = list(value) if isinstance(value, (list, tuple)) else [str(value)]
            # Be robust if legacy data mistakenly includes 'その他' in the list
            filtered = [v for v in values if str(v).strip() and str(v).strip() != "その他"]
            row[header] = _format_list_value(filtered)
        elif isinstance(value, (list, tuple)):
            row[header] = _format_list_value(value)
        else:
            row[header] = value

    # 出力
    os.makedirs(out_dir, exist_ok=True)
    ts = _dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    out_path = os.path.join(out_dir, f"contract_{ts}.csv")
    # utf-8-sig ensures BOM for Excel-friendly CSV
    with open(out_path, "w", encoding="utf-8-sig", newline="") as f_csv:
        writer = csv.DictWriter(f_csv, fieldnames=headers, extrasaction="ignore")
        writer.writeheader()
        writer.writerow(row)
    return out_path
