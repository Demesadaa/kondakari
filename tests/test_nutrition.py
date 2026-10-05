from datetime import date

import pytest

from agent.models import BodyProfile
from agent.nutrition import bmr, compute_targets, workout_kcal

YEAR = date.today().year


def profile(**overrides) -> BodyProfile:
    base = dict(sex="male", birth_year=YEAR - 30, height_cm=180, activity="moderate", goal="maintain")
    return BodyProfile(**(base | overrides))


def test_mifflin_st_jeor():
    assert bmr("male", 80, 180, 30) == 1780
    assert bmr("female", 60, 165, 25) == pytest.approx(1345.25)


def test_maintain_targets_balance_energy():
    t = compute_targets(profile(), 80)
    assert t.tdee == round(1780 * 1.55)
    assert t.kcal == round(t.tdee / 10) * 10
    assert abs(4 * t.protein_g + 4 * t.carbs_g + 9 * t.fat_g - t.kcal) < 15


def test_loss_rate_capped_and_calorie_floor_enforced():
    t = compute_targets(profile(sex="female", height_cm=155, activity="sedentary", goal="lose", weekly_rate_kg=1.0), 50)
    assert t.weekly_rate_kg == 0.5
    assert t.kcal == 1200
    assert len(t.warnings) == 2


def test_underweight_loss_warns_and_gain_is_surplus():
    assert any("BMI" in w for w in compute_targets(profile(goal="lose"), 55).warnings)
    gain = compute_targets(profile(goal="gain", weekly_rate_kg=0.25), 70)
    assert gain.kcal > gain.tdee


def test_obese_protein_uses_reference_weight():
    t = compute_targets(profile(goal="lose"), 130)
    assert t.protein_g == round(2.0 * 25 * 1.8**2)


def test_incomplete_profile_raises():
    with pytest.raises(ValueError, match="height_cm"):
        compute_targets(BodyProfile(sex="male", birth_year=1990, activity="light", goal="lose"), 80)


def test_workout_kcal():
    assert workout_kcal("running", 30, "moderate", 70) == (round(9.8 * 70 * 0.5), True)
    assert workout_kcal("morning running session", 60, "vigorous", 80)[1] is True
    assert workout_kcal("parkour", 60, "light", 80) == (240, False)
