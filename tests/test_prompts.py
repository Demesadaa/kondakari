from agent.prompts import SYSTEM_PROMPT


def test_coaching_scope_covers_core_nutrition_topics():
    required = (
        "weight loss",
        "maintenance",
        "weight gain",
        "protein",
        "carbs",
        "fat",
        "micronutrients",
        "supplements",
        "fasting",
        "body recomposition",
    )
    prompt = SYSTEM_PROMPT.lower()
    assert all(topic in prompt for topic in required)


def test_coaching_policy_separates_education_from_calculation():
    assert "General explanations do not require a tool" in SYSTEM_PROMPT
    assert "Personal calorie" in SYSTEM_PROMPT
    assert "must come from tools" in SYSTEM_PROMPT


def test_coaching_policy_contains_medical_boundaries():
    assert "Never diagnose" in SYSTEM_PROMPT
    assert "registered dietitian" in SYSTEM_PROMPT
    assert "Urgent red-flag symptoms" in SYSTEM_PROMPT


def test_exact_snacks_have_a_dedicated_tool_route():
    assert "use generate_snack_ideas, never generate_menus" in SYSTEM_PROMPT
