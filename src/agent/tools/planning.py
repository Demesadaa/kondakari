from datetime import date, timedelta

from langchain_core.tools import BaseTool, tool
from pydantic import BaseModel, Field

from agent.kitchen import Kitchen
from agent.models import Location, MealSlot
from agent.tools._common import dump


class PlanMealInput(BaseModel):
    day: date = Field(description="YYYY-MM-DD")
    meal: MealSlot
    recipe_id: str = Field(min_length=1)


class DateRangeInput(BaseModel):
    start: date | None = Field(default=None, description="First day (YYYY-MM-DD); defaults to today.")
    days: int = Field(default=7, ge=1, le=31)


class RemoveMealInput(BaseModel):
    day: date
    meal: MealSlot


class MarkBoughtInput(BaseModel):
    item_ids: list[int] = Field(min_length=1, description="Shopping list item IDs.")
    add_to_pantry: bool = Field(default=True, description="Also add the bought items to the pantry (qty 1).")
    location: Location = "pantry"


def _range(start: date | None, days: int) -> tuple[date, date]:
    first = start or date.today()
    return first, first + timedelta(days=days - 1)


def build_planning_tools(kitchen: Kitchen) -> list[BaseTool]:
    @tool("plan_meal", args_schema=PlanMealInput)
    def plan_meal(day: date, meal: MealSlot, recipe_id: str) -> str:
        """Put a recipe in the meal plan for a day and meal slot (replaces what was there). Reports missing ingredients."""
        recipe = kitchen.recipe(recipe_id)
        kitchen.recipes.plan(day, meal, recipe.id)
        return dump({"planned": {"day": day, "meal": meal, "recipe": recipe.name}, "pantry_match": kitchen.match(recipe)})

    @tool("get_meal_plan", args_schema=DateRangeInput)
    def get_meal_plan(start: date | None = None, days: int = 7) -> str:
        """Show the meal plan for a date range."""
        first, last = _range(start, days)
        return dump({"from": first, "to": last, "entries": kitchen.recipes.plan_between(first, last)})

    @tool("remove_planned_meal", args_schema=RemoveMealInput)
    def remove_planned_meal(day: date, meal: MealSlot) -> str:
        """Remove a meal from the plan."""
        return dump({"removed": kitchen.recipes.unplan(day, meal), "day": day, "meal": meal})

    @tool("generate_shopping_list", args_schema=DateRangeInput)
    def generate_shopping_list(start: date | None = None, days: int = 7) -> str:
        """Add every ingredient of the planned meals in the range that the pantry lacks to the shopping list."""
        first, last = _range(start, days)
        return dump({"shopping_list": kitchen.build_shopping_list(first, last)})

    @tool("get_shopping_list")
    def get_shopping_list() -> str:
        """Show the current shopping list."""
        return dump({"shopping_list": kitchen.shopping.items()})

    @tool("mark_items_bought", args_schema=MarkBoughtInput)
    def mark_items_bought(item_ids: list[int], add_to_pantry: bool = True, location: Location = "pantry") -> str:
        """Remove bought items from the shopping list and (by default) add them to the pantry."""
        bought = kitchen.shopping.remove(item_ids)
        if add_to_pantry:
            for item in bought:
                kitchen.pantry.add(item.name, 1, "pcs", location)
        missing = sorted(set(item_ids) - {i.id for i in bought})
        return dump({"bought": [i.name for i in bought], "unknown_ids": missing, "added_to_pantry": add_to_pantry})

    return [plan_meal, get_meal_plan, remove_planned_meal, generate_shopping_list, get_shopping_list, mark_items_bought]
