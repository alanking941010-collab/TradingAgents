"""SHFE commodity option contract specifications.

The deterministic analytics core keeps price-point outputs for auditability, but
trading/risk decisions need cash values. SHFE commodity options inherit the
underlying futures contract multiplier, so one option-price point is worth the
multiplier in CNY per lot.
"""

from __future__ import annotations

from tradingagents.options.data_loader import normalize_product

# SHFE futures/option contract multipliers. These are used to convert option
# price points into CNY cash values per lot.
_CONTRACT_MULTIPLIERS = {
    "CU": 5,      # copper: 5 tons / lot
    "AL": 5,      # aluminum: 5 tons / lot
    "ZN": 5,      # zinc: 5 tons / lot
    "PB": 5,      # lead: 5 tons / lot
    "NI": 1,      # nickel: 1 ton / lot
    "SN": 1,      # tin: 1 ton / lot
    "AU": 1000,   # gold: 1000 grams / lot
    "AG": 15,     # silver: 15 kg / lot
    "AO": 20,     # alumina: 20 tons / lot
}

_UNIT_LABELS = {
    "CU": "5 tons/lot",
    "AL": "5 tons/lot",
    "ZN": "5 tons/lot",
    "PB": "5 tons/lot",
    "NI": "1 ton/lot",
    "SN": "1 ton/lot",
    "AU": "1000 grams/lot",
    "AG": "15 kg/lot",
    "AO": "20 tons/lot",
}


def contract_multiplier_for_product(product: str) -> int:
    """Return the SHFE option contract multiplier for a product or alias."""
    normalized = normalize_product(product)
    try:
        return _CONTRACT_MULTIPLIERS[normalized]
    except KeyError as exc:
        raise ValueError(f"Unsupported SHFE option product for contract multiplier: {product!r}") from exc


def multiplier_unit_for_product(product: str) -> str:
    """Return a human-readable multiplier unit label for a product or alias."""
    normalized = normalize_product(product)
    try:
        return _UNIT_LABELS[normalized]
    except KeyError as exc:
        raise ValueError(f"Unsupported SHFE option product for multiplier unit: {product!r}") from exc
