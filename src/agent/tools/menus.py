from datetime import date

from langchain_core.tools import BaseTool, tool
from pydantic import BaseModel, Field

from agent.coach import Coach
from agent.models import Diet, MenuSet
from agent.tools._common import dump


class GenerateMenusInput(BaseModel):
    calories: float = Field(ge=1000, le=5000, description="Exact daily calorie target for every menu.")
    count: int = Field(default=3, ge=1, le=12, description="Number of different daily menus (max 12).")
    meals_per_day: int = Field(default=4, ge=3, le=5)
    diet: Diet = "omnivore"
    exclude: list[str] = Field(default_factory=list, description="Foods, ingredients or allergens to avoid, e.g. 'nuts', 'pork'.")
    protein_g: float | None = Field(default=None, gt=0, description="Daily protein target; omit to derive from the goal.")
    carbs_g: float | None = Field(default=None, ge=0)
    fat_g: float | None = Field(default=None, gt=0)


class GenerateSnacksInput(BaseModel):
    calories: float = Field(ge=100, le=1000, description="Exact calorie target for each snack option.")
    count: int = Field(default=3, ge=1, le=12, description="Number of different snack options.")
    diet: Diet = "omnivore"
    exclude: list[str] = Field(default_factory=list, description="Foods or allergens to avoid.")
    protein_g: float | None = Field(default=None, gt=0, description="Protein target for each snack, if requested.")


class LogMenuInput(BaseModel):
    menu_set_id: int = Field(ge=1)
    menu_number: int = Field(ge=1)
    day: date | None = Field(default=None, description="YYYY-MM-DD; defaults to today.")


def _compact(menu_set: MenuSet) -> dict:
    """Keeps the tool result small: the full menus are stored and shown by the /menus command."""
    return {
        "menu_set_id": menu_set.id,
        "target": menu_set.target,
        "menus": [
            {
                "menu": m.number,
                "totals": m.totals,
                "meals": [
                    {"meal": meal.meal, "kcal": round(meal.totals.kcal),
                     "items": [f"{it.food} / {it.food_ka} {it.grams:g} g" for it in meal.items]}
                    for meal in m.meals
                ],
            }
            for m in menu_set.menus
        ],
    }


def build_menu_tools(coach: Coach) -> list[BaseTool]:
    @tool("generate_menus", args_schema=GenerateMenusInput)
    def generate_menus(
        calories: float,
        count: int = 3,
        meals_per_day: int = 4,
        diet: Diet = "omnivore",
        exclude: list[str] | None = None,
        protein_g: float | None = None,
        carbs_g: float | None = None,
        fat_g: float | None = None,
    ) -> str:
        """Build up to 12 different daily menus hitting an exact calorie target and protein/carbs/fat targets, with
        gram-precise portions. Saved allergies/dislikes are excluded automatically."""
        menu_set = coach.generate_menus(calories, count, meals_per_day, diet, exclude, protein_g, carbs_g, fat_g)
        return dump(_compact(menu_set) | {"tip": "User can type /menus to see formatted tables."})

    @tool("generate_snack_ideas", args_schema=GenerateSnacksInput)
    def generate_snack_ideas(
        calories: float,
        count: int = 3,
        diet: Diet = "omnivore",
        exclude: list[str] | None = None,
        protein_g: float | None = None,
    ) -> str:
        """Build up to 12 standalone snack ideas, each hitting an exact 100-1000 kcal target with calculated
        portions and macros. Use this—not generate_menus—for exact-calorie snack requests."""
        snack_set = coach.generate_snacks(calories, count, diet, exclude, protein_g)
        return dump(_compact(snack_set))

    @tool("log_menu", args_schema=LogMenuInput)
    def log_menu(menu_set_id: int, menu_number: int, day: date | None = None) -> str:
        """Log every item of a generated menu to the food diary (when the user ate/will eat that menu)."""
        target_day = day or date.today()
        entries = coach.log_menu(menu_set_id, menu_number, target_day)
        return dump({"logged_items": len(entries), "day_consumed": coach.daily_summary(target_day)["consumed"]})

    return [generate_menus, generate_snack_ideas, log_menu]
