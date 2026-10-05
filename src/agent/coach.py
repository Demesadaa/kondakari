from dataclasses import dataclass
from datetime import date, timedelta

from agent.db import (
    FoodLogRepository,
    FoodRepository,
    MenuRepository,
    PreferenceRepository,
    ProfileRepository,
    WeightRepository,
    WorkoutRepository,
)
from agent.menus import MenuError, MenuGenerator, allowed_foods, resolve_targets
from agent.models import Diet, FoodLogEntry, Intensity, LogMeal, Macros, MenuSet, NutritionTargets, Workout
from agent.nutrition import compute_targets, workout_kcal

DEFAULT_WEIGHT_KG = 70.0


@dataclass
class Coach:
    """Nutrition & fitness services: targets, logging, summaries and menu generation."""

    foods: FoodRepository
    profile: ProfileRepository
    weights: WeightRepository
    food_log: FoodLogRepository
    workouts: WorkoutRepository
    menus: MenuRepository
    preferences: PreferenceRepository

    def current_weight(self) -> float | None:
        latest = self.weights.latest()
        return latest.weight_kg if latest else None

    def targets(self) -> NutritionTargets:
        weight = self.current_weight()
        if weight is None:
            raise ValueError("No body weight logged yet; ask the user for their weight")
        return compute_targets(self.profile.get(), weight)

    def try_targets(self) -> NutritionTargets | None:
        try:
            return self.targets()
        except ValueError:
            return None

    def setup_hint(self) -> str | None:
        missing = self.profile.get().missing_fields()
        if self.current_weight() is None:
            missing.append("weight_kg")
        return f"Profile incomplete; missing: {', '.join(missing)}" if missing else None

    def log_food(
        self, day: date, meal: LogMeal, food_name: str, grams: float | None = None, pieces: float | None = None
    ) -> FoodLogEntry:
        food = self.foods.resolve(food_name)
        if grams is None:
            if pieces is None:
                raise ValueError(f"Give grams or pieces for {food_name!r}")
            if food.piece_g is None:
                raise ValueError(f"{food.name!r} has no standard piece size; give grams instead")
            grams = pieces * food.piece_g
        return self.food_log.add(day, meal, food, grams)

    def log_workout(
        self, day: date, activity: str, minutes: float, intensity: Intensity, notes: str = ""
    ) -> tuple[Workout, list[str]]:
        notes_out = []
        weight = self.current_weight()
        if weight is None:
            weight = DEFAULT_WEIGHT_KG
            notes_out.append(f"No weight logged; estimate assumes {DEFAULT_WEIGHT_KG:g} kg.")
        kcal, known = workout_kcal(activity, minutes, intensity, weight)
        if not known:
            notes_out.append(f"Unrecognised activity {activity!r}; used a generic {intensity} estimate.")
        return self.workouts.add(day, activity, minutes, intensity, kcal, notes), notes_out

    def daily_summary(self, day: date) -> dict:
        entries = self.food_log.for_day(day)
        workouts = self.workouts.between(day, day)
        by_meal: dict[str, Macros] = {}
        for e in entries:
            by_meal[e.meal] = by_meal.get(e.meal, Macros()) + Macros(kcal=e.kcal, protein=e.protein, carbs=e.carbs, fat=e.fat)
        consumed = sum(by_meal.values(), Macros()).rounded()
        targets = self.try_targets()
        summary = {
            "day": day,
            "consumed": consumed,
            "by_meal": {k: v.rounded() for k, v in by_meal.items()},
            "entries": [{"id": e.id, "meal": e.meal, "food": e.food_name, "grams": e.grams, "kcal": round(e.kcal)}
                        for e in entries],
            "workouts": [{"activity": w.activity, "minutes": w.minutes, "kcal_burned": w.kcal_burned} for w in workouts],
            "burned_kcal": round(sum(w.kcal_burned for w in workouts)),
        }
        if targets:
            summary["targets"] = {"kcal": targets.kcal, "protein": targets.protein_g, "carbs": targets.carbs_g, "fat": targets.fat_g}
            summary["remaining"] = {
                "kcal": round(targets.kcal - consumed.kcal),
                "protein": round(targets.protein_g - consumed.protein),
                "carbs": round(targets.carbs_g - consumed.carbs),
                "fat": round(targets.fat_g - consumed.fat),
            }
        else:
            summary["hint"] = self.setup_hint()
        return summary

    def progress(self, days: int) -> dict:
        end = date.today()
        start = end - timedelta(days=days - 1)
        weights = self.weights.between(start, end)
        totals = self.food_log.daily_totals(start, end)
        workouts = self.workouts.between(start, end)
        profile = self.profile.get()
        targets = self.try_targets()

        weight: dict = {"entries": len(weights), "target_weight_kg": profile.target_weight_kg}
        if weights:
            weight |= {"start": weights[0].weight_kg, "current": weights[-1].weight_kg,
                       "change_kg": round(weights[-1].weight_kg - weights[0].weight_kg, 2)}
        if len(weights) >= 2 and weights[-1].day != weights[0].day:
            xs = [(w.day - weights[0].day).days for w in weights]
            ys = [w.weight_kg for w in weights]
            mx, my = sum(xs) / len(xs), sum(ys) / len(ys)
            slope = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / sum((x - mx) ** 2 for x in xs)
            weekly = round(slope * 7, 2)
            weight["trend_kg_per_week"] = weekly
            if profile.target_weight_kg and weekly:
                remaining = profile.target_weight_kg - weights[-1].weight_kg
                if remaining * weekly > 0:
                    weight["eta_weeks_to_target"] = round(remaining / weekly, 1)

        logged = list(totals.values())
        intake = {"logged_days": len(logged)}
        if logged:
            intake |= {"avg_kcal": round(sum(m.kcal for m in logged) / len(logged)),
                       "avg_protein": round(sum(m.protein for m in logged) / len(logged))}
        if targets:
            intake["target_kcal"] = targets.kcal
            intake["days_within_10pct_of_target"] = sum(abs(m.kcal - targets.kcal) <= 0.1 * targets.kcal for m in logged)

        return {
            "period": {"from": start, "to": end, "days": days},
            "weight": weight,
            "intake": intake,
            "workouts": {"sessions": len(workouts), "minutes": round(sum(w.minutes for w in workouts)),
                         "kcal_burned": round(sum(w.kcal_burned for w in workouts))},
        }

    def generate_menus(
        self,
        kcal: float,
        count: int = 3,
        meals_per_day: int = 4,
        diet: Diet = "omnivore",
        exclude: list[str] | None = None,
        protein: float | None = None,
        carbs: float | None = None,
        fat: float | None = None,
        seed: int | None = None,
    ) -> MenuSet:
        goal = self.profile.get().goal or "maintain"
        targets = resolve_targets(kcal, goal, protein, carbs, fat)
        # Saved allergies/dislikes are always enforced, even if the model forgets to pass them.
        prefs = self.preferences.all()
        saved = [t.strip() for key in ("allergies", "dislikes") for t in prefs.get(key, "").split(",")]
        foods = allowed_foods(self.foods.all(), diet, [*(exclude or []), *filter(None, saved)])
        if not foods:
            raise MenuError("No foods left after applying the diet and exclusions.")
        menus = MenuGenerator(foods, seed).generate(targets, count, meals_per_day)
        return self.menus.save(targets.as_macros(), diet, menus)

    def generate_snacks(
        self,
        kcal: float,
        count: int = 3,
        diet: Diet = "omnivore",
        exclude: list[str] | None = None,
        protein: float | None = None,
        seed: int | None = None,
    ) -> MenuSet:
        """Generate standalone snack options, each hitting the requested energy target."""
        targets = resolve_targets(kcal, "maintain", protein=protein)
        prefs = self.preferences.all()
        saved = [t.strip() for key in ("allergies", "dislikes") for t in prefs.get(key, "").split(",")]
        foods = allowed_foods(self.foods.all(), diet, [*(exclude or []), *filter(None, saved)])
        if not foods:
            raise MenuError("No foods left after applying the diet and exclusions.")
        snacks = MenuGenerator(foods, seed).generate(targets, count, meals_per_day=1)
        return self.menus.save(targets.as_macros(), diet, snacks)

    def log_menu(self, set_id: int, number: int, day: date) -> list[FoodLogEntry]:
        menu_set = self.menus.get(set_id)
        if menu_set is None:
            raise LookupError(f"No menu set with id {set_id}")
        menu = next((m for m in menu_set.menus if m.number == number), None)
        if menu is None:
            raise LookupError(f"Menu set {set_id} has menus 1..{len(menu_set.menus)}; got {number}")
        entries = []
        for meal in menu.meals:
            for item in meal.items:
                food = self.foods.get(item.food_id) or self.foods.resolve(item.food)
                entries.append(self.food_log.add(day, meal.meal, food, item.grams))
        return entries
