from datetime import date

from langchain_core.tools import BaseTool, tool
from pydantic import BaseModel, Field, model_validator

from agent.coach import Coach
from agent.models import Activity, Goal, Intensity, LogMeal, Sex
from agent.tools._common import dump


class UpdateProfileInput(BaseModel):
    sex: Sex | None = None
    age: int | None = Field(default=None, ge=14, le=100)
    height_cm: float | None = Field(default=None, ge=100, le=250)
    weight_kg: float | None = Field(default=None, ge=25, le=400, description="Current weight; logged for today.")
    activity: Activity | None = Field(
        default=None,
        description="sedentary (desk, no exercise), light (1-3 workouts/wk), moderate (3-5), "
                    "active (6-7), very_active (physical job + training).",
    )
    goal: Goal | None = None
    weekly_rate_kg: float | None = Field(default=None, ge=0, le=1.5, description="Desired kg/week to lose or gain.")
    target_weight_kg: float | None = Field(default=None, ge=30, le=300)


class LogWeightInput(BaseModel):
    weight_kg: float = Field(ge=25, le=400)
    day: date | None = Field(default=None, description="YYYY-MM-DD; defaults to today.")


class SearchFoodsInput(BaseModel):
    query: str = Field(min_length=1, description="Food name in English or Georgian.")


class CustomFoodInput(BaseModel):
    name: str = Field(min_length=1, description="English name.")
    name_ka: str = Field(default="", description="Georgian name, if known.")
    kcal: float = Field(ge=0, le=900, description="Per 100 g.")
    protein: float = Field(ge=0, le=100, description="Grams per 100 g.")
    carbs: float = Field(ge=0, le=100, description="Grams per 100 g.")
    fat: float = Field(ge=0, le=100, description="Grams per 100 g.")
    piece_g: float | None = Field(default=None, gt=0, description="Weight of one piece/serving in grams.")


class FoodLogItem(BaseModel):
    food: str = Field(min_length=1, description="Food name (English or Georgian) as found by search_foods.")
    meal: LogMeal
    grams: float | None = Field(default=None, gt=0, le=3000)
    pieces: float | None = Field(default=None, gt=0, le=50, description="Alternative to grams, e.g. 5 khinkali.")

    @model_validator(mode="after")
    def _amount(self) -> "FoodLogItem":
        if self.grams is None and self.pieces is None:
            raise ValueError("each item needs grams or pieces")
        return self


class LogFoodInput(BaseModel):
    items: list[FoodLogItem] = Field(min_length=1)
    day: date | None = Field(default=None, description="YYYY-MM-DD; defaults to today.")


class EntryIdInput(BaseModel):
    entry_id: int = Field(ge=1)


class LogWorkoutInput(BaseModel):
    activity: str = Field(min_length=1, description="English activity name, e.g. running, strength training, yoga.")
    minutes: float = Field(gt=0, le=600)
    intensity: Intensity = "moderate"
    day: date | None = None
    notes: str = Field(default="", description="e.g. exercises, sets, distance.")


class DayInput(BaseModel):
    day: date | None = Field(default=None, description="YYYY-MM-DD; defaults to today.")


class ProgressInput(BaseModel):
    days: int = Field(default=30, ge=2, le=365)


def build_health_tools(coach: Coach) -> list[BaseTool]:
    @tool("update_body_profile", args_schema=UpdateProfileInput)
    def update_body_profile(
        sex: Sex | None = None,
        age: int | None = None,
        height_cm: float | None = None,
        weight_kg: float | None = None,
        activity: Activity | None = None,
        goal: Goal | None = None,
        weekly_rate_kg: float | None = None,
        target_weight_kg: float | None = None,
    ) -> str:
        """Create or update the user's body profile (only the given fields change). Returns calorie/macro targets once complete."""
        if weight_kg is not None:
            coach.weights.log(date.today(), weight_kg)
        profile = coach.profile.update(
            sex=sex,
            birth_year=date.today().year - age if age is not None else None,
            height_cm=height_cm,
            activity=activity,
            goal=goal,
            weekly_rate_kg=weekly_rate_kg,
            target_weight_kg=target_weight_kg,
        )
        result = {"profile": profile.model_dump() | {"age": profile.age}, "current_weight_kg": coach.current_weight()}
        if targets := coach.try_targets():
            result["targets"] = targets
        else:
            result["hint"] = coach.setup_hint()
        return dump(result)

    @tool("get_nutrition_targets")
    def get_nutrition_targets() -> str:
        """Daily calorie and protein/carbs/fat targets with BMI, BMR, TDEE and safety warnings."""
        return dump(coach.targets())

    @tool("log_weight", args_schema=LogWeightInput)
    def log_weight(weight_kg: float, day: date | None = None) -> str:
        """Record a body-weight measurement (one per day; re-logging a day overwrites it)."""
        entry = coach.weights.log(day or date.today(), weight_kg)
        return dump({"logged": entry, "progress": coach.progress(30)["weight"]})

    @tool("search_foods", args_schema=SearchFoodsInput)
    def search_foods(query: str) -> str:
        """Look up foods in the nutrition database (per 100 g values; English or Georgian names)."""
        foods = coach.foods.search(query)
        return dump([
            {"name": f.name, "name_ka": f.name_ka, "per_100g": {"kcal": f.kcal, "protein": f.protein, "carbs": f.carbs,
                                                               "fat": f.fat}, "piece_g": f.piece_g}
            for f in foods
        ])

    @tool("add_custom_food", args_schema=CustomFoodInput)
    def add_custom_food(
        name: str, kcal: float, protein: float, carbs: float, fat: float, name_ka: str = "", piece_g: float | None = None
    ) -> str:
        """Add a food missing from the database (values per 100 g, e.g. from a package label)."""
        return dump(coach.foods.add_custom(name, kcal, protein, carbs, fat, name_ka, piece_g))

    @tool("log_food", args_schema=LogFoodInput)
    def log_food(items: list[FoodLogItem], day: date | None = None) -> str:
        """Log eaten foods (grams or pieces) to the food diary. Returns entries and the day's running totals."""
        target_day = day or date.today()
        logged = [coach.log_food(target_day, i.meal, i.food, i.grams, i.pieces) for i in items]
        summary = coach.daily_summary(target_day)
        return dump({
            "logged": [{"id": e.id, "food": e.food_name, "grams": e.grams, "kcal": round(e.kcal)} for e in logged],
            "day_consumed": summary["consumed"],
            "remaining": summary.get("remaining"),
        })

    @tool("delete_food_log_entry", args_schema=EntryIdInput)
    def delete_food_log_entry(entry_id: int) -> str:
        """Remove a mistaken food diary entry by its ID."""
        return dump({"deleted": coach.food_log.delete(entry_id)})

    @tool("log_workout", args_schema=LogWorkoutInput)
    def log_workout(
        activity: str, minutes: float, intensity: Intensity = "moderate", day: date | None = None, notes: str = ""
    ) -> str:
        """Log a workout; estimates calories burned from MET values and current body weight."""
        workout, notes_out = coach.log_workout(day or date.today(), activity, minutes, intensity, notes)
        return dump({"logged": workout, "notes": notes_out})

    @tool("get_daily_summary", args_schema=DayInput)
    def get_daily_summary(day: date | None = None) -> str:
        """Food diary for a day: totals per meal, workouts, targets and what is remaining."""
        return dump(coach.daily_summary(day or date.today()))

    @tool("get_progress", args_schema=ProgressInput)
    def get_progress(days: int = 30) -> str:
        """Progress over the last N days: weight trend (kg/week), ETA to target weight, average intake, workouts."""
        return dump(coach.progress(days))

    return [
        update_body_profile,
        get_nutrition_targets,
        log_weight,
        search_foods,
        add_custom_food,
        log_food,
        delete_food_log_entry,
        log_workout,
        get_daily_summary,
        get_progress,
    ]
