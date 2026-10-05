"""Deterministic nutrition math. The LLM explains these numbers; it never computes them."""

from agent.matching import normalize, tokens
from agent.models import BodyProfile, Goal, Intensity, NutritionTargets

ACTIVITY_FACTORS = {"sedentary": 1.2, "light": 1.375, "moderate": 1.55, "active": 1.725, "very_active": 1.9}
KCAL_PER_KG_FAT = 7700
MIN_KCAL = {"female": 1200, "male": 1500}
DEFAULT_RATE = {"lose": 0.5, "maintain": 0.0, "gain": 0.25}
MAX_GAIN_RATE = 0.5
PROTEIN_G_PER_KG = {"lose": 2.0, "maintain": 1.6, "gain": 1.8}
FAT_SHARE = 0.27
MIN_FAT_G_PER_KG = 0.6

# Compendium of Physical Activities (approximate METs at moderate effort).
METS = {
    "walking": 3.5, "brisk walking": 4.3, "hiking": 6.0, "running": 9.8, "jogging": 7.0,
    "cycling": 7.5, "swimming": 7.0, "rowing": 7.0, "elliptical": 5.0, "stairs": 8.0,
    "strength training": 5.0, "weightlifting": 5.0, "gym": 5.0, "crossfit": 8.0, "hiit": 8.0,
    "yoga": 2.5, "pilates": 3.0, "stretching": 2.3, "dancing": 5.0, "boxing": 7.8,
    "football": 7.0, "soccer": 7.0, "basketball": 6.5, "tennis": 7.3, "volleyball": 4.0,
    "martial arts": 10.0, "wrestling": 6.0, "skiing": 7.0, "jump rope": 11.0,
}
GENERIC_METS = {"light": 3.0, "moderate": 5.0, "vigorous": 8.0}
INTENSITY_FACTOR = {"light": 0.8, "moderate": 1.0, "vigorous": 1.25}


def bmi(weight_kg: float, height_cm: float) -> float:
    return round(weight_kg / (height_cm / 100) ** 2, 1)


def bmr(sex: str, weight_kg: float, height_cm: float, age: int) -> float:
    """Mifflin-St Jeor."""
    return 10 * weight_kg + 6.25 * height_cm - 5 * age + (5 if sex == "male" else -161)


def compute_targets(profile: BodyProfile, weight_kg: float) -> NutritionTargets:
    if missing := profile.missing_fields():
        raise ValueError(f"Body profile incomplete; missing: {', '.join(missing)}")

    goal: Goal = profile.goal
    warnings: list[str] = []
    body_bmi = bmi(weight_kg, profile.height_cm)
    base = bmr(profile.sex, weight_kg, profile.height_cm, profile.age)
    tdee = base * ACTIVITY_FACTORS[profile.activity]

    rate = DEFAULT_RATE[goal] if profile.weekly_rate_kg is None or goal == "maintain" else profile.weekly_rate_kg
    if goal == "lose":
        cap = round(weight_kg * 0.01, 2)
        if rate > cap:
            warnings.append(f"Requested loss rate reduced to {cap} kg/week (max ~1% of body weight).")
            rate = cap
        if body_bmi < 18.5:
            warnings.append("BMI is below 18.5; weight loss is not recommended. Consider maintain or gain.")
    elif goal == "gain" and rate > MAX_GAIN_RATE:
        warnings.append(f"Gain rate reduced to {MAX_GAIN_RATE} kg/week to limit fat gain.")
        rate = MAX_GAIN_RATE

    delta = rate * KCAL_PER_KG_FAT / 7
    kcal = tdee - delta if goal == "lose" else tdee + delta if goal == "gain" else tdee
    floor = MIN_KCAL[profile.sex]
    if kcal < floor:
        warnings.append(f"Target raised to the safe minimum of {floor} kcal/day; progress will be slower.")
        kcal = floor
    kcal = round(kcal / 10) * 10

    # For obesity, protein is based on the weight at BMI 25 to avoid excessive targets.
    reference_weight = min(weight_kg, 25 * (profile.height_cm / 100) ** 2) if body_bmi > 30 else weight_kg
    protein = PROTEIN_G_PER_KG[goal] * reference_weight
    fat = max(FAT_SHARE * kcal / 9, MIN_FAT_G_PER_KG * weight_kg)
    carbs = max((kcal - 4 * protein - 9 * fat) / 4, 0)

    return NutritionTargets(
        weight_kg=weight_kg,
        bmi=body_bmi,
        bmr=round(base),
        tdee=round(tdee),
        kcal=kcal,
        protein_g=round(protein),
        carbs_g=round(carbs),
        fat_g=round(fat),
        goal=goal,
        weekly_rate_kg=rate,
        warnings=warnings,
    )


def workout_kcal(activity: str, minutes: float, intensity: Intensity, weight_kg: float) -> tuple[int, bool]:
    """Returns (kcal burned, whether the activity was recognised)."""
    key = normalize(activity)
    met = METS.get(key)
    if met is None:
        words = tokens(key)
        met = next((m for name, m in METS.items() if tokens(name) <= words), None)
    known = met is not None
    met = met * INTENSITY_FACTOR[intensity] if known else GENERIC_METS[intensity]
    return round(met * weight_kg * minutes / 60), known
