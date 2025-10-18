from typing import List, Tuple
from models.schemas import ContractForm

REQUIRED_FIELDS = [
    "affiliation",
    "target_product",
    "activity_background",
    "counterparty_relationship",
    "activity_details",
]

def validate_form(form: ContractForm) -> Tuple[bool, List[str]]:
    missing = []
    for f in REQUIRED_FIELDS:
        if getattr(form, f) in (None, "", 0):
            missing.append(f)
    return (len(missing) == 0, missing)
