import json
import logging
from typing import Protocol

import httpx

from agent.db import ApiCache
from agent.models import Ingredient, Recipe, RecipeSummary

log = logging.getLogger(__name__)


class RecipeAPIError(Exception):
    pass


class RecipeSource(Protocol):
    def search(self, query: str) -> list[Recipe]: ...
    def filter_by_ingredient(self, ingredient: str) -> list[RecipeSummary]: ...
    def lookup(self, recipe_id: str) -> Recipe | None: ...


def parse_meal(meal: dict) -> Recipe:
    ingredients = []
    for i in range(1, 21):
        name = (meal.get(f"strIngredient{i}") or "").strip()
        if name:
            ingredients.append(Ingredient(name=name, measure=(meal.get(f"strMeasure{i}") or "").strip()))
    return Recipe(
        id=meal["idMeal"],
        name=meal["strMeal"],
        category=meal.get("strCategory") or "",
        area=meal.get("strArea") or "",
        instructions=(meal.get("strInstructions") or "").strip(),
        ingredients=ingredients,
        source_url=meal.get("strSource") or meal.get("strYoutube") or "",
    )


class MealDBClient:
    """TheMealDB (free, keyless) with a SQLite response cache and stale-cache fallback on network errors."""

    def __init__(
        self,
        cache: ApiCache,
        base_url: str = "https://www.themealdb.com/api/json/v1/1",
        ttl_seconds: float = 7 * 24 * 3600,
        timeout: float = 10.0,
    ) -> None:
        self.cache = cache
        self.base_url = base_url.rstrip("/")
        self.ttl_seconds = ttl_seconds
        self.http = httpx.Client(timeout=timeout)

    def close(self) -> None:
        self.http.close()

    def _get(self, endpoint: str, params: dict[str, str]) -> dict:
        url = str(httpx.URL(f"{self.base_url}/{endpoint}", params=params))
        if (cached := self.cache.get(url, self.ttl_seconds)) is not None:
            return json.loads(cached)
        try:
            response = self.http.get(url)
            response.raise_for_status()
            data = response.json()
        except (httpx.HTTPError, ValueError) as e:
            if (stale := self.cache.get(url)) is not None:
                log.warning("TheMealDB unavailable (%s); serving stale cache", e)
                return json.loads(stale)
            raise RecipeAPIError(f"Recipe service unavailable: {e}") from e
        self.cache.put(url, json.dumps(data))
        return data

    def search(self, query: str) -> list[Recipe]:
        return [parse_meal(m) for m in self._get("search.php", {"s": query.strip()}).get("meals") or []]

    def filter_by_ingredient(self, ingredient: str) -> list[RecipeSummary]:
        slug = "_".join(ingredient.lower().split())
        meals = self._get("filter.php", {"i": slug}).get("meals") or []
        return [RecipeSummary(id=m["idMeal"], name=m["strMeal"]) for m in meals]

    def lookup(self, recipe_id: str) -> Recipe | None:
        meals = self._get("lookup.php", {"i": recipe_id.strip()}).get("meals") or []
        return parse_meal(meals[0]) if meals else None
