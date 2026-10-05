from langchain_core.tools import BaseTool, ToolException, tool
from pydantic import BaseModel, Field

from agent.kitchen import Kitchen
from agent.tools._common import dump
from agent.units import convert


class SetPreferenceInput(BaseModel):
    key: str = Field(min_length=1, description="e.g. diet, allergies, dislikes, household_size, favorite_cuisines.")
    value: str = Field(min_length=1)


class RemovePreferenceInput(BaseModel):
    key: str = Field(min_length=1)


class ConvertUnitsInput(BaseModel):
    quantity: float
    from_unit: str = Field(min_length=1, description="e.g. g, kg, oz, lb, ml, l, tsp, tbsp, cup.")
    to_unit: str = Field(min_length=1)


def build_profile_tools(kitchen: Kitchen) -> list[BaseTool]:
    @tool("set_preference", args_schema=SetPreferenceInput)
    def set_preference(key: str, value: str) -> str:
        """Remember a lasting user preference (overwrites the same key). It is shown to you in every conversation."""
        kitchen.preferences.set(key, value)
        return dump({"saved": True, "preferences": kitchen.preferences.all()})

    @tool("remove_preference", args_schema=RemovePreferenceInput)
    def remove_preference(key: str) -> str:
        """Forget a saved user preference."""
        return dump({"removed": kitchen.preferences.delete(key), "preferences": kitchen.preferences.all()})

    @tool("convert_units", args_schema=ConvertUnitsInput)
    def convert_units(quantity: float, from_unit: str, to_unit: str) -> str:
        """Convert cooking quantities between mass units or between volume units (exact arithmetic)."""
        try:
            result = convert(quantity, from_unit, to_unit)
        except ValueError as e:
            raise ToolException(str(e)) from e
        return dump({"quantity": result, "unit": to_unit})

    return [set_preference, remove_preference, convert_units]
