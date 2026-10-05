from langchain_core.tools import BaseTool, tool
from pydantic import BaseModel, Field

from agent.kitchen import Kitchen
from agent.tools._common import dump


class SearchRecipesInput(BaseModel):
    query: str = Field(min_length=1, description="Dish name or keyword, e.g. 'curry', 'pancakes'.")


class IngredientInput(BaseModel):
    ingredient: str = Field(min_length=1, description="One main ingredient, e.g. 'chicken breast'.")


class RecipeIdInput(BaseModel):
    recipe_id: str = Field(min_length=1, description="Recipe ID from a previous tool result.")


class SuggestInput(BaseModel):
    limit: int = Field(default=5, ge=1, le=10)


class SaveRecipeInput(RecipeIdInput):
    rating: int | None = Field(default=None, ge=1, le=5)
    notes: str | None = Field(default=None, description="The user's own notes, e.g. 'less chili next time'.")


def build_recipe_tools(kitchen: Kitchen) -> list[BaseTool]:
    @tool("search_recipes", args_schema=SearchRecipesInput)
    def search_recipes(query: str) -> str:
        """Search recipes by dish name or keyword."""
        results = kitchen.source.search(query)[:10]
        return dump({
            "count": len(results),
            "recipes": [{"id": r.id, "name": r.name, "category": r.category, "area": r.area} for r in results],
        })

    @tool("find_recipes_by_ingredient", args_schema=IngredientInput)
    def find_recipes_by_ingredient(ingredient: str) -> str:
        """Find recipes that use a specific main ingredient."""
        results = kitchen.source.filter_by_ingredient(ingredient)[:15]
        return dump({"count": len(results), "recipes": results})

    @tool("get_recipe", args_schema=RecipeIdInput)
    def get_recipe(recipe_id: str) -> str:
        """Get full recipe details (ingredients, instructions) plus which ingredients the pantry has or is missing."""
        recipe = kitchen.recipe(recipe_id)
        return dump({"recipe": recipe, "pantry_match": kitchen.match(recipe)})

    @tool("suggest_recipes_from_pantry", args_schema=SuggestInput)
    def suggest_recipes_from_pantry(limit: int = 5) -> str:
        """Suggest recipes cookable from the current pantry, ranked by use of soon-expiring items and coverage."""
        suggestions = kitchen.suggest(limit)
        if not suggestions:
            return dump({"suggestions": [], "hint": "Pantry is empty or no recipes matched; add items first."})
        return dump({"suggestions": suggestions})

    @tool("save_recipe", args_schema=SaveRecipeInput)
    def save_recipe(recipe_id: str, rating: int | None = None, notes: str | None = None) -> str:
        """Save a recipe to the user's favourites, optionally with a 1-5 rating and personal notes."""
        kitchen.recipe(recipe_id)
        saved = kitchen.recipes.mark_favorite(recipe_id, rating, notes)
        return dump({"saved": {"id": saved.id, "name": saved.name, "rating": saved.rating, "notes": saved.notes}})

    @tool("list_saved_recipes")
    def list_saved_recipes() -> str:
        """List the user's favourite recipes with ratings and notes."""
        favorites = kitchen.recipes.favorites()
        return dump([{"id": r.id, "name": r.name, "rating": r.rating, "notes": r.notes} for r in favorites])

    return [
        search_recipes,
        find_recipes_by_ingredient,
        get_recipe,
        suggest_recipes_from_pantry,
        save_recipe,
        list_saved_recipes,
    ]
