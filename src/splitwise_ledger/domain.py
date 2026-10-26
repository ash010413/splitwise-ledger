"""Financial normalization and conservative categorization, independent of HTTP and storage."""

import hashlib
import json
from decimal import Decimal, InvalidOperation
from enum import StrEnum


class Category(StrEnum):
    HOME = "Home"
    CAR = "Car"
    TRAVEL = "Flights / Travel"
    DINING = "Food / Dining"
    GROCERIES = "Groceries"
    MISC = "Misc"
    ENTERTAINMENT = "Movie / Entertainment"
    PHONE = "Phone"
    AI = "AI"
    SPORTS = "Badminton / Sports"
    GYM = "Gym"
    LUX = "Lux"


def normalize_description(value: str) -> str:
    return " ".join(value.casefold().split())


def amount(value: str) -> str:
    try:
        parsed = Decimal(str(value))
    except InvalidOperation as exc:
        raise ValueError("Invalid monetary amount") from exc
    if not parsed.is_finite():
        raise ValueError("Non-finite monetary amount")
    return format(parsed, "f")


def normalize_expense(raw: dict, user_id: int) -> dict:
    """Use consumption (owed_share), never payment or net balance. Fail closed on missing data."""
    excluded = bool(raw.get("deleted_at") or raw.get("payment"))
    shares = [u for u in raw.get("users", []) if u.get("user_id") == user_id]
    if not excluded and len(shares) != 1:
        raise ValueError("Expense must contain exactly one share for the connected user")
    share = amount(shares[0]["owed_share"]) if shares and not excluded else "0"
    record = {
        "id": int(raw["id"]),
        "description": raw.get("description", ""),
        "details": raw.get("details") or "",
        "date": raw["date"],
        "currency": raw["currency_code"],
        "my_share": share,
        "total_cost": amount(raw["cost"]),
        "group_id": raw.get("group_id"),
        "source_category": raw.get("category"),
        "excluded": excluded or Decimal(share) == 0,
    }
    # Includes every field that can affect a user's category decision.
    record["revision"] = hashlib.sha256(
        json.dumps(record, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return record


def classify(record: dict, rules: list[dict]) -> tuple[str | None, str]:
    if record["excluded"]:
        return None, "excluded"
    matches = [
        rule
        for rule in rules
        if normalize_description(record["description"]) == rule["description"]
        and record["group_id"] == rule["group_id"]
        and record["currency"] == rule["currency"]
    ]
    categories = {rule["category"] for rule in matches}
    if len(categories) == 1:
        return categories.pop(), "approved_rule"
    return None, "conflicting_rules" if matches else "needs_review"
