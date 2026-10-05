import sqlite3
from datetime import date, timedelta

import pytest

from agent.db.connection import MIGRATIONS
from agent.models import Recipe

TODAY = date.today()


def test_migrate_is_idempotent(db):
    db.migrate()
    assert db.schema_version == len(MIGRATIONS)


def test_schema_constraints_reject_bad_data(db):
    with pytest.raises(sqlite3.IntegrityError), db.connect() as conn:
        conn.execute("INSERT INTO pantry_items (name, quantity, location) VALUES ('milk', 1, 'garage')")
    with pytest.raises(sqlite3.IntegrityError), db.connect() as conn:
        conn.execute("INSERT INTO pantry_items (name, quantity) VALUES ('milk', -2)")


def test_pantry_merges_identical_items(kitchen):
    kitchen.pantry.add("Eggs", 6, expires_on=TODAY)
    merged = kitchen.pantry.add(" eggs ", 4, expires_on=TODAY)
    kitchen.pantry.add("eggs", 12)  # different expiry -> separate batch
    assert merged.quantity == 10
    assert len(kitchen.pantry.search("egg")) == 2


def test_pantry_expiry_filter_and_order(kitchen):
    kitchen.pantry.add("rice", 1, "kg")
    kitchen.pantry.add("milk", 1, "l", "fridge", TODAY + timedelta(days=5))
    kitchen.pantry.add("spinach", 1, location="fridge", expires_on=TODAY + timedelta(days=1))
    assert [i.name for i in kitchen.pantry.search()] == ["spinach", "milk", "rice"]
    assert [i.name for i in kitchen.pantry.search(expiring_within_days=3)] == ["spinach"]


def test_pantry_use_deducts_then_deletes(kitchen):
    item = kitchen.pantry.add("flour", 1000, "g")
    assert kitchen.pantry.use(item.id, 300).quantity == 700
    assert kitchen.pantry.use(item.id, 700) is None
    with pytest.raises(LookupError):
        kitchen.pantry.use(item.id, 1)


def test_recipe_upsert_keeps_user_data_and_plan_replaces_slot(kitchen):
    kitchen.recipes.upsert(Recipe(id="9", name="Soup"))
    kitchen.recipes.mark_favorite("9", rating=5, notes="add garlic")
    kitchen.recipes.upsert(Recipe(id="9", name="Tomato Soup"))
    saved = kitchen.recipes.get("9")
    assert (saved.name, saved.rating, saved.notes) == ("Tomato Soup", 5, "add garlic")

    kitchen.recipes.upsert(Recipe(id="10", name="Salad"))
    kitchen.recipes.plan(TODAY, "dinner", "9")
    kitchen.recipes.plan(TODAY, "dinner", "10")
    [entry] = kitchen.recipes.plan_between(TODAY, TODAY)
    assert entry.recipe_name == "Salad"


def test_shopping_merge_is_idempotent(kitchen):
    kitchen.shopping.add("Milk", "1 l for Pancakes")
    kitchen.shopping.add("milk", "1 l for Pancakes")
    kitchen.shopping.add("milk", "200 ml for Curry")
    [item] = kitchen.shopping.items()
    assert item.detail == "1 l for Pancakes; 200 ml for Curry"
    assert kitchen.shopping.remove([item.id, 999])[0].name == "milk"


def test_preferences_normalise_keys(kitchen):
    kitchen.preferences.set("Household Size", "2")
    kitchen.preferences.set("household_size", "3")
    assert kitchen.preferences.all() == {"household_size": "3"}


def test_cache_ttl(cache):
    cache.put("k", "v")
    assert cache.get("k", max_age_seconds=60) == "v"
    assert cache.get("k", max_age_seconds=-1) is None
    assert cache.get("k") == "v"


def test_thread_titled_from_first_message_only(threads):
    thread = threads.create()
    threads.touch(thread.id, first_message="Plan my week\nplease")
    threads.touch(thread.id, first_message="Something else")
    assert threads.get(thread.id).title == "Plan my week please"
