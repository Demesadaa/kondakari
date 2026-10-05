"""Daily menu construction: pick diverse foods per meal slot, then solve portion sizes so the day
hits the calorie target exactly (to a few kcal) and the macro targets closely."""

import random
from collections import Counter
from dataclasses import dataclass

import numpy as np
from scipy.optimize import lsq_linear

from agent.matching import tokens
from agent.models import Diet, Food, Goal, LogMeal, Macros, Menu, MenuItem, MenuMeal

SLOTS: dict[int, list[LogMeal]] = {
    1: ["snack"],
    3: ["breakfast", "lunch", "dinner"],
    4: ["breakfast", "lunch", "snack", "dinner"],
    5: ["breakfast", "snack", "lunch", "snack", "dinner"],
}
SLOT_SHARE = {"breakfast": 0.25, "lunch": 0.35, "dinner": 0.30, "snack": 0.10}
TEMPLATES: dict[LogMeal, list[list[str]]] = {
    "breakfast": [
        ["breakfast_protein", "breakfast_carb", "fruit"],
        ["breakfast_protein", "breakfast_carb", "breakfast_fat"],
        ["breakfast_protein", "breakfast_carb", "veg"],
    ],
    "lunch": [["protein", "carb", "veg", "cooking_fat"], ["dish", "veg"]],
    "dinner": [["protein", "carb", "veg", "cooking_fat"], ["protein", "veg", "veg", "cooking_fat"], ["dish", "veg"]],
    "snack": [
        ["snack", "fruit"],
        ["breakfast_protein", "breakfast_carb", "fruit"],
        ["snack", "breakfast_carb"],
        ["breakfast_protein", "fruit", "breakfast_fat"],
    ],
}
DIET_EXCLUDED_TAGS: dict[Diet, set[str]] = {
    "omnivore": set(),
    "pescatarian": {"meat"},
    "vegetarian": {"meat", "fish"},
    "vegan": {"meat", "fish", "dairy", "egg", "honey"},
}
MACRO_SPLIT: dict[Goal, tuple[float, float, float]] = {  # protein, carbs, fat share of kcal
    "lose": (0.35, 0.35, 0.30),
    "maintain": (0.30, 0.40, 0.30),
    "gain": (0.30, 0.45, 0.25),
}
KCAL_PER_G = {"protein": 4, "carbs": 4, "fat": 9}

W_KCAL, W_MACRO, W_MEAL, W_REG = 10.0, 1.0, 0.4, 0.05
KCAL_TOLERANCE = 0.01
MACRO_TOLERANCE = 0.12
MAX_ATTEMPTS = 40


class MenuError(ValueError):
    pass


@dataclass(frozen=True)
class MenuTargets:
    kcal: float
    protein: float
    carbs: float
    fat: float

    def as_macros(self) -> Macros:
        return Macros(kcal=self.kcal, protein=self.protein, carbs=self.carbs, fat=self.fat).rounded()


def resolve_targets(
    kcal: float, goal: Goal = "maintain", protein: float | None = None, carbs: float | None = None,
    fat: float | None = None,
) -> MenuTargets:
    """Fill unspecified macros from the goal's default split, keeping total energy equal to kcal."""
    p_share, c_share, f_share = MACRO_SPLIT[goal]
    defaults = {"protein": kcal * p_share / 4, "carbs": kcal * c_share / 4, "fat": kcal * f_share / 9}
    values = {"protein": protein, "carbs": carbs, "fat": fat}
    missing = [k for k, v in values.items() if v is None]

    if not missing:
        implied = sum(values[k] * KCAL_PER_G[k] for k in values)
        if abs(implied - kcal) / kcal > 0.08:
            raise MenuError(
                f"Macros imply {implied:.0f} kcal (4*P + 4*C + 9*F) but {kcal:.0f} kcal was requested; "
                "adjust one of them or leave a macro unspecified."
            )
        return MenuTargets(kcal, protein, carbs, fat)

    balance = next(k for k in ("carbs", "fat", "protein") if k in missing)
    for k in missing:
        if k != balance:
            values[k] = defaults[k]
    rest = kcal - sum(values[k] * KCAL_PER_G[k] for k in values if k != balance)
    if rest < 0:
        raise MenuError(f"The requested macros exceed {kcal:.0f} kcal and leave no room for {balance}.")
    values[balance] = rest / KCAL_PER_G[balance]
    return MenuTargets(kcal, values["protein"], values["carbs"], values["fat"])


def _excluded_by_terms(food: Food, terms: list[frozenset[str]]) -> bool:
    names = [tokens(n) for n in (food.name, food.name_ka, *food.aliases) if n]
    tags = frozenset(t for tag in food.tags for t in tokens(tag))
    return any(term <= n for term in terms for n in names) or any(term <= tags for term in terms)


def allowed_foods(foods: list[Food], diet: Diet, exclude: list[str]) -> list[Food]:
    banned = DIET_EXCLUDED_TAGS[diet]
    terms = [t for t in (tokens(e) for e in exclude) if t]
    return [f for f in foods if f.roles and not banned & set(f.tags) and not _excluded_by_terms(f, terms)]


class MenuGenerator:
    def __init__(self, foods: list[Food], seed: int | None = None) -> None:
        self.rng = random.Random(seed)
        self.pools: dict[str, list[Food]] = {}
        for food in foods:
            for role in food.roles:
                self.pools.setdefault(role, []).append(food)
        self.uses: Counter[int] = Counter()

    def generate(self, targets: MenuTargets, count: int, meals_per_day: int) -> list[Menu]:
        slots = SLOTS[meals_per_day]
        menus: list[Menu] = []
        signatures: set[frozenset[int]] = set()
        for number in range(1, count + 1):
            best, best_score = None, float("inf")
            for _ in range(MAX_ATTEMPTS):
                meals = self._compose(slots)
                signature = frozenset(f.id for _, items in meals for f in items if f.category in {"protein", "dish", "carb"})
                duplicate = signature in signatures
                menu = self._build(number, meals, self._solve(meals, targets))
                # Repeats are allowed only as a last resort (tiny food pools under strict diets).
                score = self._score(menu.totals, targets) + (1.0 if duplicate else 0.0)
                if score < best_score:
                    best, best_score = (menu, signature, meals), score
                if not duplicate and self._acceptable(menu.totals, targets):
                    break
            menu, signature, meals = best
            signatures.add(signature)
            self.uses.update(f.id for _, items in meals for f in items)
            menus.append(menu)
        return menus

    def _pick(self, role: str, taken: set[int]) -> Food | None:
        pool = [f for f in self.pools.get(role, []) if f.id not in taken]
        if not pool:
            return None
        weights = [1 / (1 + self.uses[f.id]) ** 2 for f in pool]
        return self.rng.choices(pool, weights)[0]

    def _compose(self, slots: list[LogMeal]) -> list[tuple[LogMeal, list[Food]]]:
        meals, taken = [], set()
        for slot in slots:
            options = [t for t in TEMPLATES[slot] if all(self.pools.get(r) for r in t)]
            if not options:
                raise MenuError(f"Not enough foods to build a {slot} with these restrictions.")
            items = []
            for role in self.rng.choice(options):
                if food := self._pick(role, taken):
                    items.append(food)
                    taken.add(food.id)
            meals.append((slot, items))
        return meals

    @staticmethod
    def _solve(meals: list[tuple[LogMeal, list[Food]]], t: MenuTargets) -> list[float]:
        flat = [(mi, f) for mi, (_, items) in enumerate(meals) for f in items]
        kcal = np.array([f.kcal / 100 for _, f in flat])
        protein = np.array([f.protein / 100 for _, f in flat])
        carbs = np.array([f.carbs / 100 for _, f in flat])
        fat = np.array([f.fat / 100 for _, f in flat])
        lo = np.array([f.min_g for _, f in flat])
        hi = np.array([f.max_g for _, f in flat])

        share_total = sum(SLOT_SHARE[slot] for slot, _ in meals)
        rows = [W_KCAL * kcal, W_MACRO * 4 * protein, W_MACRO * 4 * carbs, W_MACRO * 9 * fat]
        rhs = [W_KCAL * t.kcal, W_MACRO * 4 * t.protein, W_MACRO * 4 * t.carbs, W_MACRO * 9 * t.fat]
        for mi, (slot, _) in enumerate(meals):
            mask = np.array([1.0 if m == mi else 0.0 for m, _ in flat])
            rows.append(W_MEAL * kcal * mask)
            rhs.append(W_MEAL * t.kcal * SLOT_SHARE[slot] / share_total)
        rows.extend(W_REG * np.eye(len(flat)))
        rhs.extend(W_REG * (lo + hi) / 2)

        x = lsq_linear(np.vstack(rows), np.array(rhs), bounds=(lo, hi)).x

        # Round to kitchen-friendly amounts, then correct the calorie residual on the most flexible items.
        grams = []
        for (_, f), g in zip(flat, x):
            step = 1 if f.kcal >= 500 else 5
            grams.append(float(min(max(round(g / step) * step, f.min_g), f.max_g)))
        residual = t.kcal - sum(g * f.kcal / 100 for (_, f), g in zip(flat, grams))
        order = sorted(range(len(flat)), key=lambda i: ({"carb": 0, "protein": 1, "dish": 1}.get(flat[i][1].category, 2)))
        for i in order:
            f = flat[i][1]
            per_g = f.kcal / 100
            if per_g <= 0 or abs(residual) < per_g:
                continue
            new = float(min(max(round(grams[i] + residual / per_g), f.min_g), f.max_g))
            residual -= (new - grams[i]) * per_g
            grams[i] = new
        return grams

    @staticmethod
    def _build(number: int, meals: list[tuple[LogMeal, list[Food]]], grams: list[float]) -> Menu:
        it = iter(grams)
        built = []
        for slot, items in meals:
            menu_items = []
            for food in items:
                g = next(it)
                menu_items.append(
                    MenuItem(food_id=food.id, food=food.name, food_ka=food.name_ka, grams=g, macros=food.macros(g).rounded())
                )
            built.append(MenuMeal(meal=slot, items=menu_items))
        totals = sum((m.totals for m in built), Macros()).rounded()
        return Menu(number=number, meals=built, totals=totals)

    @staticmethod
    def _errors(totals: Macros, t: MenuTargets) -> tuple[float, float]:
        kcal_err = abs(totals.kcal - t.kcal) / t.kcal
        macro_err = max(
            abs(totals.protein - t.protein) / max(t.protein, 1),
            abs(totals.carbs - t.carbs) / max(t.carbs, 1),
            abs(totals.fat - t.fat) / max(t.fat, 1),
        )
        return kcal_err, macro_err

    def _score(self, totals: Macros, t: MenuTargets) -> float:
        kcal_err, macro_err = self._errors(totals, t)
        return 5 * kcal_err + macro_err

    def _acceptable(self, totals: Macros, t: MenuTargets) -> bool:
        kcal_err, macro_err = self._errors(totals, t)
        return kcal_err <= KCAL_TOLERANCE and macro_err <= MACRO_TOLERANCE
