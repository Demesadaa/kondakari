from langchain_core.tools import BaseTool

from agent.coach import Coach
from agent.kitchen import Kitchen
from agent.tools.health import build_health_tools
from agent.tools.menus import build_menu_tools
from agent.tools.pantry import build_pantry_tools
from agent.tools.planning import build_planning_tools
from agent.tools.profile import build_profile_tools
from agent.tools.recipes import build_recipe_tools


def build_tools(kitchen: Kitchen, coach: Coach) -> list[BaseTool]:
    return [
        *build_pantry_tools(kitchen),
        *build_recipe_tools(kitchen),
        *build_planning_tools(kitchen),
        *build_profile_tools(kitchen),
        *build_health_tools(coach),
        *build_menu_tools(coach),
    ]


__all__ = ["build_tools"]
