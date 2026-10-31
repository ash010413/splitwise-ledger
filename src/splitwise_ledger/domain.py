"""Financial normalization and conservative categorization, independent of HTTP and storage."""

import hashlib
import json
import re
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
    OTHERS = "Others"


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
    excluded = bool(
        raw.get("deleted_at")
        or raw.get("payment")
        or raw.get("creation_method") == "debt_consolidation"
    )
    users = raw.get("users", [])
    shares = [u for u in users if u.get("user_id") == user_id]
    if not excluded and not shares:
        # Group history includes expenses involving only other members. Persist an
        # excluded record so an edit removing our share also removes old spending.
        # An absent/malformed participant list is still an import error.
        if not users or any(
            not isinstance(u.get("user_id"), int) or "owed_share" not in u for u in users
        ):
            raise ValueError("Expense has an invalid participant list")
        excluded = True
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


# Deliberately omit broad categories such as Insurance, Electronics and General:
# these cannot distinguish the user's Home/Car or necessary/discretionary spending.
SOURCE_CATEGORIES = {
    "rent": Category.HOME,
    "electricity": Category.HOME,
    "water": Category.HOME,
    "heat/gas": Category.HOME,
    "trash": Category.HOME,
    "car": Category.CAR,
    "gas/fuel": Category.CAR,
    "parking": Category.CAR,
    "plane": Category.TRAVEL,
    "hotel": Category.TRAVEL,
    "dining out": Category.DINING,
    "groceries": Category.GROCERIES,
    "movies": Category.ENTERTAINMENT,
    "entertainment - other": Category.ENTERTAINMENT,
    "sports": Category.SPORTS,
}

# Whole words/phrases only. Apply the user's Costco grocery default below,
# after specific purchase-purpose signals; other broad merchants remain ambiguous.
DESCRIPTION_PATTERNS = {
    Category.HOME: (
        r"\b(rent|renters? insurance|electricity|electric bills?|elec\.?([ -]+bills?)?|"
        r"water bills?|utilities|"
        r"utility bill|home internet|internet bill|wifi bill)\b"
    ),
    Category.CAR: (
        r"\b(fuel|petrol|gas station|costco gas|car wash|car insurance|auto insurance|parking)\b"
    ),
    Category.TRAVEL: (
        r"\b(flight|flights|airfare|airline|hotel|airbnb|car rental|"
        r"rental car|car rent|rent a car)\b"
    ),
    Category.DINING: r"\b(breakfast|lunch|dinner|restaurant|dining out|takeout)\b",
    Category.GROCERIES: r"\b(grocery|groceries)\b",
    Category.ENTERTAINMENT: r"\b(movie|movies|cinema|concert tickets?)\b",
    Category.PHONE: r"\b(phone bill|mobile bill|icloud)\b",
    Category.AI: (
        r"\b(chatgpt|openai subscription|claude pro|claude subscription|gemini advanced|"
        r"gemini subscription|perplexity pro|cursor pro)\b"
    ),
    Category.SPORTS: (
        r"\b(badminton|pickleball|tennis court|sports court|running shoes|sports shoes)\b"
    ),
    Category.GYM: r"\b(gym membership|gym subscription|gym fees?)\b",
}


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
    if matches:
        return None, "conflicting_rules"
    description = normalize_description(record["description"])
    signals = {
        category
        for category, pattern in DESCRIPTION_PATTERNS.items()
        if re.search(pattern, description)
    }
    source = SOURCE_CATEGORIES.get(
        (record.get("source_category") or {}).get("name", "").casefold().strip()
    )
    if source:
        signals.add(source)
    # The owner's taxonomy explicitly treats ordinary Costco shopping as groceries.
    # Specific evidence (fuel, source category, non-food items) wins over this default.
    if (
        not signals
        and re.search(r"\bcostco\b", description)
        and not re.search(
            r"\b(gas|electronics?|tv|television|laptop|headphones|furniture|tires?|tyres?|"
            r"clothing|clothes|shoes|membership|pizza|food court|hot dogs?|appliances?)\b",
            description,
        )
    ):
        signals.add(Category.GROCERIES)
    # These phrases explicitly suggest a different purpose than a bare keyword.
    # Never guess Misc/Lux, or auto-file a mixed purchase in just one category.
    if re.search(r"\b(gift|gifts|reimbursement|refund|mixed|stock|stocks)\b", description):
        return None, "needs_review"
    if len(signals) > 1:
        return None, "conflicting_signals"
    if len(signals) == 1:
        return signals.pop().value, "splitwise_category" if source else "description_rule"
    return None, "needs_review"
