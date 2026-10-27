"""Three-scenario profit/loss. Prices and yields are ranges, not point guesses."""
from ..data import Crop


def scenarios(crop: Crop, land_decimal: float, penalty_pct: float) -> dict:
    factor = 1 - penalty_pct / 100
    cost = crop.cost * land_decimal
    out = {"cost": round(cost)}
    for i, name in enumerate(("bad", "base", "good")):
        revenue = crop.y[i] * factor * crop.p[i] * land_decimal
        out[name] = {"revenue": round(revenue), "profit": round(revenue - cost)}
    base_yield = crop.y[1] * factor * land_decimal
    out["breakeven_price"] = round(cost / base_yield, 1) if base_yield > 0 else None
    out["margin_pct"] = round(out["base"]["profit"] / cost * 100, 1) if cost else 0.0
    return out
