from collections import Counter
from dataclasses import dataclass
from datetime import date

from agent.db import PantryRepository, PreferenceRepository, RecipeRepository, ShoppingRepository
from agent.matching import is_staple, matches, normalize
from agent.mealdb import RecipeSource
from agent.models import PantryItem, Recipe, RecipeMatch, ShoppingItem

EXPIRING_DAYS = 3


@dataclass
class Kitchen:
    """Domain services on top of the repositories; tools stay thin wrappers around this."""

    pantry: PantryRepository
    recipes: RecipeRepository
    shopping: ShoppingRepository
    preferences: PreferenceRepository
    source: RecipeSource

    def recipe(self, recipe_id: str) -> Recipe:
        """Local copy first, then the API (and store it so plans/favorites can reference it)."""
        if saved := self.recipes.get(recipe_id):
            return saved
        recipe = self.source.lookup(recipe_id)
        if recipe is None:
            raise LookupError(f"No recipe with id {recipe_id!r}; search for recipes to get valid IDs")
        self.recipes.upsert(recipe)
        return recipe

    def match(self, recipe: Recipe, pantry: list[PantryItem] | None = None) -> RecipeMatch:
        pantry = self.pantry.search() if pantry is None else pantry
        have, missing, expiring = [], [], set()
        for ingredient in recipe.ingredients:
            item = next((p for p in pantry if matches(p.name, ingredient.name)), None)
            if item or is_staple(ingredient.name):
                have.append(ingredient.name)
            else:
                missing.append(f"{ingredient.name} ({ingredient.measure})" if ingredient.measure else ingredient.name)
            if item and item.days_left is not None and item.days_left <= EXPIRING_DAYS:
                expiring.add(item.name)
        total = len(recipe.ingredients)
        return RecipeMatch(
            recipe_id=recipe.id,
            name=recipe.name,
            coverage=round(len(have) / total, 2) if total else 0.0,
            have=have,
            missing=missing,
            uses_expiring=sorted(expiring),
        )

    def suggest(self, limit: int = 5, seed_count: int = 4, max_lookups: int = 10) -> list[RecipeMatch]:
        """Rank recipes by how many soon-to-expire items they use, then by pantry coverage."""
        pantry = self.pantry.search()
        if not pantry:
            return []
        seeds = list(dict.fromkeys(p.name for p in pantry))[:seed_count]
        hits: Counter[str] = Counter()
        for seed in seeds:
            hits.update(summary.id for summary in self.source.filter_by_ingredient(seed))
        ranked = [self.match(self.recipe(rid), pantry) for rid, _ in hits.most_common(max_lookups)]
        ranked.sort(key=lambda m: (len(m.uses_expiring), m.coverage), reverse=True)
        return ranked[:limit]

    def build_shopping_list(self, start: date, end: date) -> list[ShoppingItem]:
        pantry = self.pantry.search()
        for entry in self.recipes.plan_between(start, end):
            recipe = self.recipe(entry.recipe_id)
            for ingredient in recipe.ingredients:
                if is_staple(ingredient.name) or any(matches(p.name, ingredient.name) for p in pantry):
                    continue
                detail = f"{ingredient.measure} for {recipe.name}" if ingredient.measure else f"for {recipe.name}"
                self.shopping.add(normalize(ingredient.name), detail)
        return self.shopping.items()
