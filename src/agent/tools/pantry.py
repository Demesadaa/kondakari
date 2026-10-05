from datetime import date

from langchain_core.tools import BaseTool, tool
from pydantic import BaseModel, Field

from agent.kitchen import Kitchen
from agent.models import Location
from agent.tools._common import dump


class PantryItemInput(BaseModel):
    name: str = Field(min_length=1, description="Ingredient name, e.g. 'eggs', 'chicken breast'.")
    quantity: float = Field(gt=0)
    unit: str = Field(default="pcs", description="e.g. pcs, g, kg, ml, l, pack, can.")
    location: Location = "pantry"
    expires_on: date | None = Field(default=None, description="Expiry date YYYY-MM-DD, if known.")


class AddPantryItemsInput(BaseModel):
    items: list[PantryItemInput] = Field(min_length=1)


class ListPantryInput(BaseModel):
    query: str = Field(default="", description="Filter by name; empty lists everything.")
    location: Location | None = None
    expiring_within_days: int | None = Field(default=None, ge=0, description="Only items expiring within N days.")


class UsePantryItemInput(BaseModel):
    item_id: int = Field(ge=1)
    quantity: float | None = Field(
        default=None, gt=0, description="Amount used, in the item's unit. Omit to remove the item entirely."
    )


def build_pantry_tools(kitchen: Kitchen) -> list[BaseTool]:
    @tool("add_pantry_items", args_schema=AddPantryItemsInput)
    def add_pantry_items(items: list[PantryItemInput]) -> str:
        """Add one or more groceries to the pantry. Identical items (same name, unit, location, expiry) are merged."""
        return dump([kitchen.pantry.add(**item.model_dump()) for item in items])

    @tool("list_pantry", args_schema=ListPantryInput)
    def list_pantry(query: str = "", location: Location | None = None, expiring_within_days: int | None = None) -> str:
        """List pantry items, soonest-expiring first. Optionally filter by name, location or days until expiry."""
        items = kitchen.pantry.search(query, location, expiring_within_days)
        return dump({"count": len(items), "items": items})

    @tool("use_pantry_item", args_schema=UsePantryItemInput)
    def use_pantry_item(item_id: int, quantity: float | None = None) -> str:
        """Deduct a used amount from a pantry item, or remove it entirely (finished, thrown away) by omitting quantity."""
        remaining = kitchen.pantry.use(item_id, quantity)
        return dump({"item_id": item_id, "removed": remaining is None, "remaining": remaining})

    return [add_pantry_items, list_pantry, use_pantry_item]
