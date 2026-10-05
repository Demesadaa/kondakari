_MASS_G = {"mg": 0.001, "g": 1.0, "kg": 1000.0, "oz": 28.3495, "lb": 453.592}
_VOLUME_ML = {"ml": 1.0, "l": 1000.0, "tsp": 4.92892, "tbsp": 14.7868, "fl oz": 29.5735, "cup": 240.0, "pint": 473.176}

_ALIASES = {
    "milligram": "mg", "milligrams": "mg",
    "gram": "g", "grams": "g", "gr": "g",
    "kilogram": "kg", "kilograms": "kg", "kilo": "kg", "kilos": "kg",
    "ounce": "oz", "ounces": "oz",
    "pound": "lb", "pounds": "lb", "lbs": "lb",
    "milliliter": "ml", "milliliters": "ml", "millilitre": "ml", "millilitres": "ml",
    "liter": "l", "liters": "l", "litre": "l", "litres": "l",
    "teaspoon": "tsp", "teaspoons": "tsp",
    "tablespoon": "tbsp", "tablespoons": "tbsp",
    "cups": "cup", "pints": "pint", "floz": "fl oz",
}


def _canonical(unit: str) -> str:
    u = " ".join(unit.lower().replace(".", "").split())
    return _ALIASES.get(u, u)


def convert(quantity: float, from_unit: str, to_unit: str) -> float:
    src, dst = _canonical(from_unit), _canonical(to_unit)
    for table in (_MASS_G, _VOLUME_ML):
        if src in table and dst in table:
            return round(quantity * table[src] / table[dst], 4)
    known = sorted(_MASS_G | _VOLUME_ML)
    if src in known and dst in known:
        raise ValueError(f"Cannot convert between mass and volume ({from_unit} -> {to_unit}) without a density")
    raise ValueError(f"Unknown unit in {from_unit!r} -> {to_unit!r}. Supported: {', '.join(known)}")
