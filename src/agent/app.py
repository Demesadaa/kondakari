import sqlite3
from dataclasses import dataclass
from pathlib import Path

from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph.state import CompiledStateGraph

from agent.coach import Coach
from agent.config import Settings
from agent.db import (
    ApiCache,
    Database,
    FoodLogRepository,
    FoodRepository,
    MenuRepository,
    PantryRepository,
    PreferenceRepository,
    ProfileRepository,
    RecipeRepository,
    ShoppingRepository,
    ThreadRepository,
    WeightRepository,
    WorkoutRepository,
)
from agent.graph import build_graph
from agent.kitchen import Kitchen
from agent.llm import build_fallback_llms, build_llm
from agent.mealdb import MealDBClient
from agent.prompts import build_system_prompt
from agent.tools import build_tools

FOODS_SEED = Path(__file__).parent / "data" / "foods.json"


@dataclass
class AgentApp:
    settings: Settings
    graph: CompiledStateGraph
    threads: ThreadRepository
    kitchen: Kitchen
    coach: Coach
    _mealdb: MealDBClient
    _checkpoint_conn: sqlite3.Connection

    def config_for(self, thread_id: str) -> dict:
        return {"configurable": {"thread_id": thread_id}, "recursion_limit": self.settings.max_agent_steps}

    def close(self) -> None:
        self._mealdb.close()
        self._checkpoint_conn.close()


def build_domain(db: Database, mealdb: MealDBClient) -> tuple[Kitchen, Coach]:
    preferences = PreferenceRepository(db)
    kitchen = Kitchen(
        pantry=PantryRepository(db),
        recipes=RecipeRepository(db),
        shopping=ShoppingRepository(db),
        preferences=preferences,
        source=mealdb,
    )
    foods = FoodRepository(db)
    foods.seed(FOODS_SEED)
    coach = Coach(
        foods=foods,
        profile=ProfileRepository(db),
        weights=WeightRepository(db),
        food_log=FoodLogRepository(db),
        workouts=WorkoutRepository(db),
        menus=MenuRepository(db),
        preferences=preferences,
    )
    return kitchen, coach


def create_app(settings: Settings) -> AgentApp:
    """Composition root: the only place that wires concrete dependencies together."""
    llm = build_llm(settings)
    db = Database(settings.app_db_path)
    db.migrate()

    mealdb = MealDBClient(
        ApiCache(db),
        base_url=settings.mealdb_base_url,
        ttl_seconds=settings.recipe_cache_ttl_hours * 3600,
        timeout=settings.http_timeout_seconds,
    )
    kitchen, coach = build_domain(db, mealdb)

    # Conversation state (messages per thread) lives in its own DB, managed by LangGraph.
    checkpoint_conn = sqlite3.connect(settings.checkpoint_db_path, check_same_thread=False)

    graph = build_graph(
        llm,
        build_tools(kitchen, coach),
        system_prompt=lambda: build_system_prompt(kitchen, coach),
        checkpointer=SqliteSaver(checkpoint_conn),
        fallback_llms=build_fallback_llms(settings),
    )
    return AgentApp(settings, graph, ThreadRepository(db), kitchen, coach, mealdb, checkpoint_conn)
