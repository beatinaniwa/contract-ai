from typing import List, Tuple
from ..models.schemas import ContractForm

REQUIRED_FIELDS = [
    "project_name",
    "counterparty_name",
    "amount_jpy",
]

def validate_form(form: ContractForm) -> Tuple[bool, List[str]]:
    missing = []
    for f in REQUIRED_FIELDS:
        if getattr(form, f) in (None, "", 0):
            missing.append(f)
    return (len(missing) == 0, missing)
