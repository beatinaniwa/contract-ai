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


def _set_checkbox(row: Dict[str, Any], mapping: Dict[str, str], selected: str | None) -> None:
    """Populate 1/0 values for a checkbox group.

    mapping: { option_label -> column_header }
    selected: currently selected label (or None)
    """
    for option, col in mapping.items():
        row[col] = 1 if (selected == option) else 0


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
        else:
            row[header] = value

    # 2) Counterparty (1社目のみアプリの入力から埋める)
    row[cfg["counterparty"]["name_cols"][0]] = form_data.get("counterparty_name", "")
    row[cfg["counterparty"]["addr_cols"][0]] = form_data.get("counterparty_address", "")

    # 相手区分チェックボックス (1社目)
    cp_types_map: Dict[str, str] = cfg["counterparty"]["type_cols"][0]
    _set_checkbox(row, cp_types_map, form_data.get("counterparty_type"))

    # 2社目/3社目は空のまま。チェックボックスは0で初期化
    for idx in (1, 2):
        for _, col in cfg["counterparty"]["type_cols"][idx].items():
            row[col] = 0

    # 3) 契約書式チェックボックス
    contract_form_cols: Dict[str, str] = cfg.get("contract_form_cols", {})
    _set_checkbox(row, contract_form_cols, form_data.get("contract_form"))

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

