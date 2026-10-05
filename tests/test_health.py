import json
from datetime import date, timedelta

import pytest
from pydantic import ValidationError

from agent.tools import build_tools

TODAY = date.today()


@pytest.fixture
def tools(kitchen, coach):
    return {t.name: t for t in build_tools(kitchen, coach)}


def call(tool, **args):
    return json.loads(tool.invoke(args))


def test_foods_are_seeded_idempotently_and_user_foods_survive(coach):
    from agent.app import FOODS_SEED

    count = len(coach.foods.all())
    coach.foods.add_custom("protein bar", 350, 30, 35, 10)
    coach.foods.seed(FOODS_SEED)
    assert len(coach.foods.all()) == count + 1
    assert coach.foods.resolve("protein bar").source == "user"


@pytest.mark.parametrize(("query", "expected"), [
    ("chicken", "chicken breast"), ("ხინკალი", "khinkali"), ("egg", "eggs"), ("მაწონი", "matsoni"),
    ("ლობიო", "lobio stew"), ("Oatmeal", "oats"),
])
def test_food_resolution_english_and_georgian(coach, query, expected):
    assert coach.foods.resolve(query).name == expected


def test_unknown_food_suggests_alternatives(coach):
    with pytest.raises(LookupError, match="khinkali"):
        coach.foods.resolve("khinkaly")


def test_profile_flow_produces_targets(tools):
    partial = call(tools["update_body_profile"], sex="male", age=29, weight_kg=88)
    assert "height_cm" in partial["hint"]
    full = call(tools["update_body_profile"], height_cm=182, activity="moderate", goal="lose", target_weight_kg=80)
    assert full["targets"]["kcal"] < full["targets"]["tdee"]


def test_log_food_with_pieces_and_georgian_names(tools, profiled_coach):
    result = call(tools["log_food"], items=[
        {"food": "ხინკალი", "meal": "lunch", "pieces": 5},
        {"food": "tomato", "meal": "lunch", "grams": 150},
    ])
    assert result["logged"][0]["grams"] == 275
    assert result["logged"][0]["kcal"] == round(220 * 2.75)
    assert result["remaining"]["kcal"] == profiled_coach.targets().kcal - result["day_consumed"]["kcal"]


def test_log_food_validation(tools):
    with pytest.raises(ValidationError):
        tools["log_food"].invoke({"items": [{"food": "rice", "meal": "lunch"}]})
    with pytest.raises(ValueError, match="piece"):
        tools["log_food"].invoke({"items": [{"food": "rice", "meal": "lunch", "pieces": 2}]})


def test_delete_food_entry(tools):
    logged = call(tools["log_food"], items=[{"food": "apple", "meal": "snack", "pieces": 1}])
    call(tools["delete_food_log_entry"], entry_id=logged["logged"][0]["id"])
    assert call(tools["get_daily_summary"])["entries"] == []


def test_workout_uses_logged_weight(tools, profiled_coach):
    result = call(tools["log_workout"], activity="running", minutes=60)
    assert result["logged"]["kcal_burned"] == pytest.approx(9.8 * 85, abs=1)
    assert result["notes"] == []


def test_progress_trend_and_eta(profiled_coach):
    profiled_coach.profile.update(target_weight_kg=80)
    for i, w in enumerate([87, 86.5, 86, 85.5, 85]):
        profiled_coach.weights.log(TODAY - timedelta(days=28 - 7 * i), w)
    progress = profiled_coach.progress(30)
    assert progress["weight"]["trend_kg_per_week"] == -0.5
    assert progress["weight"]["eta_weeks_to_target"] == 10.0


def test_generate_menus_tool_is_compact(tools):
    result = call(tools["generate_menus"], calories=2000, count=2)
    assert result["menu_set_id"] >= 1
    first_item = result["menus"][0]["meals"][0]["items"][0]
    assert " / " in first_item and first_item.endswith(" g")


def test_generate_snack_ideas_tool_uses_single_snack_slot(tools):
    result = call(tools["generate_snack_ideas"], calories=500, count=3)
    assert len(result["menus"]) == 3
    assert all(option["meals"][0]["meal"] == "snack" for option in result["menus"])
    assert all(abs(option["totals"]["kcal"] - 500) <= 5 for option in result["menus"])
