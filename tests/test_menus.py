import pytest

from agent.menus import MenuError, allowed_foods, resolve_targets


def all_foods(menu_set):
    return [item for m in menu_set.menus for meal in m.meals for item in meal.items]


@pytest.mark.parametrize(("kcal", "meals"), [(1600, 3), (2100, 4), (2800, 5)])
def test_twelve_menus_hit_exact_calories(coach, kcal, meals):
    menu_set = coach.generate_menus(kcal, count=12, meals_per_day=meals, seed=7)
    assert len(menu_set.menus) == 12
    for menu in menu_set.menus:
        assert abs(menu.totals.kcal - kcal) <= kcal * 0.01, menu.totals
        assert len(menu.meals) == meals
        assert all(m.items for m in menu.meals)


def test_menus_meet_macros_closely(coach):
    menu_set = coach.generate_menus(2000, count=6, protein=150, seed=1)
    for menu in menu_set.menus:
        assert abs(menu.totals.protein - 150) <= 150 * 0.15


def test_menus_are_diverse(coach):
    menu_set = coach.generate_menus(2200, count=12, seed=3)
    mains = [frozenset(i.food for meal in m.meals for i in meal.items) for m in menu_set.menus]
    assert len(set(mains)) == 12
    assert len({i.food for i in all_foods(menu_set)}) >= 30


def test_exact_calorie_snack_options(coach):
    snack_set = coach.generate_snacks(500, count=3, seed=8)
    assert len(snack_set.menus) == 3
    for option in snack_set.menus:
        assert len(option.meals) == 1
        assert option.meals[0].meal == "snack"
        assert abs(option.totals.kcal - 500) <= 5
        assert len(option.meals[0].items) >= 2


def test_diet_and_exclusions(coach):
    vegan = coach.generate_menus(1800, count=4, diet="vegan", seed=2)
    banned = {"meat", "fish", "dairy", "egg", "honey"}
    for item in all_foods(vegan):
        assert not banned & set(coach.foods.get(item.food_id).tags), item.food

    no_pork_nuts = coach.generate_menus(2000, count=6, exclude=["pork", "nuts"], seed=4)
    for item in all_foods(no_pork_nuts):
        tags = set(coach.foods.get(item.food_id).tags)
        assert not {"pork", "nuts"} & tags, item.food


def test_saved_allergies_are_enforced_automatically(coach):
    coach.preferences.set("allergies", "egg, peanuts")
    menu_set = coach.generate_menus(2000, count=8, seed=5)
    names = {i.food for i in all_foods(menu_set)}
    assert not names & {"eggs", "egg whites", "peanut butter", "adjaruli khachapuri"}


def test_georgian_exclusion_terms(coach):
    foods = allowed_foods(coach.foods.all(), "omnivore", ["ხინკალი", "ქათმის მკერდი"])
    assert not {"khinkali", "chicken breast"} & {f.name for f in foods}
    assert "chicken thigh" in {f.name for f in foods}


def test_menu_set_is_persisted_and_loggable(coach):
    menu_set = coach.generate_menus(1900, count=2, seed=6)
    assert coach.menus.get().id == menu_set.id
    entries = coach.log_menu(menu_set.id, 2, __import__("datetime").date.today())
    assert round(sum(e.kcal for e in entries)) == pytest.approx(menu_set.menus[1].totals.kcal, abs=3)
    with pytest.raises(LookupError):
        coach.log_menu(menu_set.id, 9, __import__("datetime").date.today())


def test_resolve_targets():
    t = resolve_targets(2000, "maintain")
    assert round(4 * t.protein + 4 * t.carbs + 9 * t.fat) == 2000
    t = resolve_targets(2000, "maintain", protein=180, fat=60)
    assert t.carbs == pytest.approx((2000 - 720 - 540) / 4)
    with pytest.raises(MenuError, match="imply"):
        resolve_targets(2000, protein=200, carbs=300, fat=100)
    with pytest.raises(MenuError, match="no room"):
        resolve_targets(1200, protein=300, fat=80)
