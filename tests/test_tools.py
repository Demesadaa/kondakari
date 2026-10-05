import json
from datetime import date, timedelta

import pytest
from langchain_core.tools import ToolException
from pydantic import ValidationError

from agent.tools import build_tools


@pytest.fixture
def tools(kitchen, coach):
    return {t.name: t for t in build_tools(kitchen, coach)}


def call(tool, **args):
    return json.loads(tool.invoke(args))


def test_every_tool_has_a_description(tools):
    assert len(tools) >= 25
    assert all(t.description for t in tools.values())


def test_add_list_and_use_pantry(tools):
    tomorrow = (date.today() + timedelta(days=1)).isoformat()
    added = call(tools["add_pantry_items"], items=[
        {"name": "eggs", "quantity": 6},
        {"name": "spinach", "quantity": 1, "location": "fridge", "expires_on": tomorrow},
    ])
    assert added[1]["days_left"] == 1

    listed = call(tools["list_pantry"], expiring_within_days=2)
    assert [i["name"] for i in listed["items"]] == ["spinach"]

    used = call(tools["use_pantry_item"], item_id=added[0]["id"], quantity=2)
    assert used["remaining"]["quantity"] == 4


def test_invalid_arguments_are_rejected(tools):
    with pytest.raises(ValidationError):
        tools["add_pantry_items"].invoke({"items": [{"name": "milk", "quantity": -1}]})
    with pytest.raises(ValidationError):
        tools["add_pantry_items"].invoke({"items": [{"name": "milk", "quantity": 1, "location": "garage"}]})


def test_plan_meal_then_shopping_list_then_buy(tools):
    today = date.today().isoformat()
    planned = call(tools["plan_meal"], day=today, meal="dinner", recipe_id="2")
    assert planned["pantry_match"]["coverage"] == 0

    shopping = call(tools["generate_shopping_list"])["shopping_list"]
    assert {i["name"] for i in shopping} == {"chicken breast", "coconut milk", "curry powder"}

    bought = call(tools["mark_items_bought"], item_ids=[shopping[0]["id"], 999])
    assert bought["unknown_ids"] == [999]
    assert call(tools["list_pantry"])["count"] == 1


def test_save_and_list_favourites(tools):
    call(tools["save_recipe"], recipe_id="1", rating=5, notes="great")
    assert call(tools["list_saved_recipes"]) == [{"id": "1", "name": "Spinach Omelette", "rating": 5, "notes": "great"}]


def test_preferences_and_units(tools):
    assert call(tools["set_preference"], key="allergies", value="peanuts")["preferences"] == {"allergies": "peanuts"}
    assert call(tools["convert_units"], quantity=1, from_unit="lb", to_unit="g")["quantity"] == 453.592
    with pytest.raises(ToolException):
        tools["convert_units"].invoke({"quantity": 1, "from_unit": "cup", "to_unit": "kg"})


def test_unknown_ids_raise(tools):
    with pytest.raises(LookupError):
        tools["use_pantry_item"].invoke({"item_id": 123})
    with pytest.raises(LookupError):
        tools["get_recipe"].invoke({"recipe_id": "nope"})
