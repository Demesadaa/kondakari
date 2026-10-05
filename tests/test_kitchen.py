from datetime import date, timedelta

import httpx
import pytest

from agent.matching import matches
from agent.mealdb import MealDBClient, RecipeAPIError
from agent.units import convert

TODAY = date.today()


@pytest.mark.parametrize(
    ("pantry", "ingredient", "expected"),
    [("eggs", "Egg", True), ("chicken", "Chicken Breast", True), ("tomatoes", "tomato", True),
     ("fresh spinach", "Spinach", True), ("potatoes", "Potato", True), ("olive oil", "Olive Oil", True),
     ("salt", "Salted Butter", False), ("beef", "Chicken", False)],
)
def test_ingredient_matching(pantry, ingredient, expected):
    assert matches(pantry, ingredient) is expected


def test_unit_conversion():
    assert convert(1, "kg", "grams") == 1000
    assert convert(2, "cups", "ml") == 480
    with pytest.raises(ValueError, match="density"):
        convert(1, "cup", "g")
    with pytest.raises(ValueError, match="Unknown unit"):
        convert(1, "handful", "g")


def test_match_reports_have_missing_and_expiring(kitchen):
    kitchen.pantry.add("eggs", 6)
    kitchen.pantry.add("spinach", 1, location="fridge", expires_on=TODAY + timedelta(days=1))
    result = kitchen.match(kitchen.recipe("1"))
    assert result.coverage == 1.0 and result.missing == [] and result.uses_expiring == ["spinach"]


def test_suggest_prefers_expiring_ingredients(kitchen):
    kitchen.pantry.add("chicken breast", 500, "g")
    kitchen.pantry.add("coconut milk", 1, "can")
    kitchen.pantry.add("spinach", 1, location="fridge", expires_on=TODAY)
    ranked = kitchen.suggest()
    assert [m.name for m in ranked] == ["Spinach Omelette", "Chicken Curry"]


def test_recipe_is_fetched_once_then_served_locally(kitchen, source):
    kitchen.recipe("2")
    kitchen.recipe("2")
    assert source.lookups == ["2"]
    with pytest.raises(LookupError):
        kitchen.recipe("404")


def test_shopping_list_from_plan_skips_pantry_and_staples(kitchen):
    kitchen.pantry.add("eggs", 6)
    kitchen.recipes.upsert(kitchen.recipe("1"))
    kitchen.recipes.plan(TODAY, "breakfast", "1")
    items = kitchen.build_shopping_list(TODAY, TODAY)
    assert [(i.name, i.detail) for i in items] == [("spinach", "1 cup for Spinach Omelette")]


def test_mealdb_uses_cache_and_falls_back_to_stale_on_network_error(cache):
    payload = {"meals": [{"idMeal": "7", "strMeal": "Pie", "strIngredient1": "Flour", "strMeasure1": "200g"}]}
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(200, json=payload)
        raise httpx.ConnectError("offline")

    client = MealDBClient(cache, ttl_seconds=3600)
    client.http = httpx.Client(transport=httpx.MockTransport(handler))

    assert client.lookup("7").ingredients[0].measure == "200g"
    assert client.lookup("7").name == "Pie"  # fresh cache hit, no request
    assert calls["n"] == 1

    client.ttl_seconds = -1  # force expiry -> network fails -> stale cache
    assert client.lookup("7").name == "Pie"
    with pytest.raises(RecipeAPIError):
        client.lookup("8")
