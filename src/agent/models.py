from datetime import date
from typing import Literal

from pydantic import BaseModel, Field, computed_field

Location = Literal["fridge", "freezer", "pantry"]
MealSlot = Literal["breakfast", "lunch", "dinner"]
LogMeal = Literal["breakfast", "lunch", "dinner", "snack"]
Sex = Literal["male", "female"]
Activity = Literal["sedentary", "light", "moderate", "active", "very_active"]
Goal = Literal["lose", "maintain", "gain"]
Intensity = Literal["light", "moderate", "vigorous"]
Diet = Literal["omnivore", "pescatarian", "vegetarian", "vegan"]


class PantryItem(BaseModel):
    id: int
    name: str
    quantity: float
    unit: str
    location: Location
    expires_on: date | None = None

    @computed_field
    @property
    def days_left(self) -> int | None:
        return None if self.expires_on is None else (self.expires_on - date.today()).days


class Ingredient(BaseModel):
    name: str
    measure: str = ""


class RecipeSummary(BaseModel):
    id: str
    name: str


class Recipe(RecipeSummary):
    category: str = ""
    area: str = ""
    instructions: str = ""
    ingredients: list[Ingredient] = Field(default_factory=list)
    source_url: str = ""


class SavedRecipe(Recipe):
    favorite: bool = False
    rating: int | None = None
    notes: str = ""


class MealPlanEntry(BaseModel):
    day: date
    meal: MealSlot
    recipe_id: str
    recipe_name: str


class ShoppingItem(BaseModel):
    id: int
    name: str
    detail: str


class RecipeMatch(BaseModel):
    recipe_id: str
    name: str
    coverage: float = Field(description="Share of ingredients already available, 0..1")
    have: list[str]
    missing: list[str]
    uses_expiring: list[str]


class Macros(BaseModel):
    kcal: float = 0
    protein: float = 0
    carbs: float = 0
    fat: float = 0

    def __add__(self, other: "Macros") -> "Macros":
        return Macros(
            kcal=self.kcal + other.kcal,
            protein=self.protein + other.protein,
            carbs=self.carbs + other.carbs,
            fat=self.fat + other.fat,
        )

    def rounded(self) -> "Macros":
        return Macros(
            kcal=round(self.kcal), protein=round(self.protein, 1), carbs=round(self.carbs, 1), fat=round(self.fat, 1)
        )


class Food(BaseModel):
    """Nutrition values are per 100 g."""

    id: int
    name: str
    name_ka: str = ""
    aliases: list[str] = Field(default_factory=list)
    kcal: float
    protein: float
    carbs: float
    fat: float
    category: str
    roles: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    min_g: float = 30
    max_g: float = 300
    piece_g: float | None = None
    source: str = "seed"

    def macros(self, grams: float) -> Macros:
        f = grams / 100
        return Macros(kcal=self.kcal * f, protein=self.protein * f, carbs=self.carbs * f, fat=self.fat * f)


class BodyProfile(BaseModel):
    sex: Sex | None = None
    birth_year: int | None = None
    height_cm: float | None = None
    activity: Activity | None = None
    goal: Goal | None = None
    weekly_rate_kg: float | None = None
    target_weight_kg: float | None = None

    @property
    def age(self) -> int | None:
        return None if self.birth_year is None else date.today().year - self.birth_year

    def missing_fields(self) -> list[str]:
        required = {"sex": self.sex, "age": self.birth_year, "height_cm": self.height_cm,
                    "activity": self.activity, "goal": self.goal}
        return [k for k, v in required.items() if v is None]


class NutritionTargets(BaseModel):
    weight_kg: float
    bmi: float
    bmr: int
    tdee: int
    kcal: int
    protein_g: int
    carbs_g: int
    fat_g: int
    goal: Goal
    weekly_rate_kg: float
    warnings: list[str] = Field(default_factory=list)


class WeightEntry(BaseModel):
    day: date
    weight_kg: float


class FoodLogEntry(BaseModel):
    id: int
    day: date
    meal: LogMeal
    food_name: str
    grams: float
    kcal: float
    protein: float
    carbs: float
    fat: float


class Workout(BaseModel):
    id: int
    day: date
    activity: str
    minutes: float
    intensity: Intensity
    kcal_burned: float
    notes: str = ""


class MenuItem(BaseModel):
    food_id: int
    food: str
    food_ka: str
    grams: float
    macros: Macros


class MenuMeal(BaseModel):
    meal: LogMeal
    items: list[MenuItem]

    @property
    def totals(self) -> Macros:
        return sum((i.macros for i in self.items), Macros())


class Menu(BaseModel):
    number: int
    meals: list[MenuMeal]
    totals: Macros


class MenuSet(BaseModel):
    id: int
    target: Macros
    diet: Diet
    menus: list[Menu]
    created_at: str = ""
