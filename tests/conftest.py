from datetime import date

import pytest

from agent.app import build_domain
from agent.coach import Coach
from agent.db import ApiCache, Database, ThreadRepository
from agent.kitchen import Kitchen
from agent.models import Ingredient, Recipe, RecipeSummary

RECIPES = {
    "1": Recipe(
        id="1",
        name="Spinach Omelette",
        ingredients=[Ingredient(name="Eggs", measure="3"), Ingredient(name="Spinach", measure="1 cup"),
                     Ingredient(name="Salt", measure="pinch")],
    ),
    "2": Recipe(
        id="2",
        name="Chicken Curry",
        ingredients=[Ingredient(name="Chicken Breast", measure="500g"), Ingredient(name="Coconut Milk", measure="1 can"),
                     Ingredient(name="Curry Powder", measure="2 tbsp")],
    ),
}


class FakeRecipeSource:
    """Offline stand-in for TheMealDB."""

    def __init__(self) -> None:
        self.lookups: list[str] = []

    def search(self, query: str) -> list[Recipe]:
        return [r for r in RECIPES.values() if query.lower() in r.name.lower()]

    def filter_by_ingredient(self, ingredient: str) -> list[RecipeSummary]:
        return [
            RecipeSummary(id=r.id, name=r.name)
            for r in RECIPES.values()
            if any(ingredient.lower() in i.name.lower() for i in r.ingredients)
        ]

    def lookup(self, recipe_id: str) -> Recipe | None:
        self.lookups.append(recipe_id)
        return RECIPES.get(recipe_id)


@pytest.fixture
def db(tmp_path) -> Database:
    database = Database(tmp_path / "test.db")
    database.migrate()
    return database


@pytest.fixture
def threads(db) -> ThreadRepository:
    return ThreadRepository(db)


@pytest.fixture
def cache(db) -> ApiCache:
    return ApiCache(db)


@pytest.fixture
def source() -> FakeRecipeSource:
    return FakeRecipeSource()


@pytest.fixture
def domain(db, source) -> tuple[Kitchen, Coach]:
    return build_domain(db, source)


@pytest.fixture
def kitchen(domain) -> Kitchen:
    return domain[0]


@pytest.fixture
def coach(domain) -> Coach:
    return domain[1]


@pytest.fixture
def profiled_coach(coach) -> Coach:
    coach.profile.update(sex="male", birth_year=date.today().year - 30, height_cm=180, activity="moderate", goal="lose")
    coach.weights.log(date.today(), 85)
    return coach
