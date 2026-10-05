# ქონდაქარი engineering walkthrough

This document explains how the agent is assembled, why each layer exists, and how a message travels from the user interface to deterministic domain code and back.

## 1. Design goals

ქონდაქარი was designed around six engineering goals:

1. **Agentic behavior** — the model must dynamically decide whether to answer or call a tool.
2. **Reliable numbers** — calories, macros, exercise energy, and progress must be calculated by code.
3. **Persistent memory** — conversations and structured user data must survive restarts.
4. **Separation of concerns** — UI, orchestration, tools, domain logic, and SQL should not be mixed.
5. **Bilingual use** — English and Georgian should share the same underlying records and workflows.
6. **Graceful failure** — bad tool calls, provider outages, invalid credentials, and interrupted turns should not crash the application.

## 2. Composition root

`src/agent/app.py` is the composition root. It is the only module responsible for choosing concrete implementations and wiring them together.

At startup it:

1. validates environment settings,
2. creates and migrates the application database,
3. constructs repositories,
4. seeds the bilingual food database,
5. constructs the recipe API client,
6. constructs `Kitchen` and `Coach` domain services,
7. initializes the primary and fallback chat models,
8. builds all LangChain tools,
9. opens LangGraph’s SQLite checkpointer,
10. compiles the state graph,
11. returns one `AgentApp` object to the selected client.

The clients never build repositories or tools themselves. This keeps the CLI and Streamlit UI behavior consistent.

## 3. Layered architecture

```text
┌──────────────────────────────────────────────────────────┐
│ Presentation                                             │
│ Streamlit web client · Rich CLI                          │
├──────────────────────────────────────────────────────────┤
│ Agent orchestration                                      │
│ LangGraph state · prompt context · model fallback        │
├──────────────────────────────────────────────────────────┤
│ Tool adapters                                            │
│ Pydantic input schema · JSON result · ToolException      │
├──────────────────────────────────────────────────────────┤
│ Domain services                                          │
│ Kitchen · Coach · menu optimizer · nutrition formulas    │
├──────────────────────────────────────────────────────────┤
│ Repositories and integrations                            │
│ SQLite repositories · TheMealDB client · API cache       │
├──────────────────────────────────────────────────────────┤
│ Persistence                                              │
│ app.db · checkpoints.db                                  │
└──────────────────────────────────────────────────────────┘
```

Dependencies point downward. A repository does not know about Streamlit, and nutrition formulas do not know about LangChain.

## 4. The LangGraph state machine

The graph state contains one field:

```python
class AgentState(TypedDict):
    messages: Annotated[list[AnyMessage], add_messages]
```

`add_messages` gives LangGraph append-and-merge semantics while preserving tool-call IDs.

### Nodes

#### `agent`

- Calls the dynamic system-prompt function.
- Repairs any unanswered historical tool calls left by interruption.
- Sends the system message plus thread history to the bound model.
- Returns one `AIMessage`.

#### `tools`

- Uses LangGraph’s `ToolNode`.
- Resolves the requested tool by name.
- Validates arguments against the tool’s Pydantic schema.
- Executes the tool.
- Converts errors into a structured `ToolMessage` so the model can correct its arguments.

#### `repair`

- Handles malformed model tool calls, such as invalid JSON.
- Inserts a focused message that describes the parser error.
- Sends control back to the model for a corrected call.

### Routing

After `agent`:

- valid tool calls route to `tools`,
- invalid tool calls route to `repair`,
- normal text ends the turn.

After `tools` or `repair`, control returns to `agent`.

The graph-level recursion limit stops pathological loops.

## 5. Dynamic system context

The system prompt is built again on every model step. It includes changing context that should not be copied into every user message:

- current date,
- saved allergies and preferences,
- body profile and current weight,
- computed daily targets,
- today’s consumed macros,
- pantry items approaching expiry.

The policy separates two kinds of responses:

### General education

The model may directly explain concepts such as:

- why protein matters,
- fasting trade-offs,
- meal timing,
- fibre and hydration,
- sustainable deficits,
- supplement evidence.

### Personal calculations

The model must call tools for:

- calorie and macro targets,
- BMI/BMR/TDEE,
- food intake totals,
- workout energy,
- progress trends,
- exact menus and snacks.

This boundary gives natural conversation without sacrificing numerical reliability.

## 6. Model initialization and failover

Provider selection is entirely configuration-driven:

```dotenv
LLM_MODEL=google_genai:gemini-3.8-flash
LLM_FALLBACK_MODELS=google_genai:gemini-3.7-flash,google_genai:gemini-3.6-flash
```

Each model is initialized through LangChain’s provider-agnostic `init_chat_model`.

For remote providers:

- request duration is bounded,
- repeated retries against one overloaded model are disabled by default,
- fallback models are attempted in order,
- low reasoning effort reduces latency for ordinary coaching tasks.

Provider errors are normalized into actionable UI messages. Tracebacks are retained in `data/agent.log`.

## 7. Tool design

Tools are thin adapters. A good tool in this project:

1. has one clear responsibility,
2. uses a Pydantic input model,
3. explains when the model should use it,
4. delegates to a domain service or repository,
5. returns structured JSON,
6. raises a clear domain error on invalid state.

Example flow:

```text
generate_snack_ideas tool
  → Coach.generate_snacks
    → resolve_targets
    → allergy/diet filtering
    → MenuGenerator
      → bounded least-squares
    → MenuRepository.save
  → compact JSON result
```

The model never receives a database connection and never writes SQL.

## 8. Repository layer

Each domain area has a focused repository:

- `PantryRepository`
- `RecipeRepository`
- `ShoppingRepository`
- `PreferenceRepository`
- `FoodRepository`
- `ProfileRepository`
- `WeightRepository`
- `FoodLogRepository`
- `WorkoutRepository`
- `MenuRepository`
- `ThreadRepository`
- `ApiCache`

Repository methods return Pydantic domain models rather than raw tuples.

All queries use parameters. The shared `Database.connect()` context manager:

- enables foreign keys,
- commits successful operations,
- rolls back exceptions,
- closes connections deterministically.

## 9. Schema migrations

Migrations are append-only SQL strings. `PRAGMA user_version` records the last applied migration.

Startup compares the current version with the migration list and applies only missing entries inside transactions.

This allows a user’s database to evolve without deleting diary or pantry data.

## 10. Food data and bilingual matching

`src/agent/data/foods.json` contains the seed catalog.

Each record can include:

- canonical English name,
- Georgian name,
- alternate aliases,
- macros per 100 g,
- food category,
- menu roles,
- diet/allergen tags,
- minimum and maximum portions,
- optional weight per piece.

The food repository refreshes seed records idempotently. Records created by the user are marked `source=user` and are never overwritten by seeding.

Matching normalizes case and whitespace, tokenizes Unicode letters, singularizes simple English plurals, and checks English names, Georgian names, and aliases.

## 11. Nutrition engine

`nutrition.py` is pure domain code and can be tested without an LLM or database.

### BMR

Mifflin–St Jeor:

```text
male:   10W + 6.25H - 5A + 5
female: 10W + 6.25H - 5A - 161
```

Where:

- `W` is kilograms,
- `H` is centimeters,
- `A` is age.

### TDEE

```text
TDEE = BMR × activity factor
```

### Goal adjustment

```text
daily calorie adjustment = weekly kg change × 7700 / 7
```

Loss subtracts the adjustment; gain adds it.

Safety rules cap weekly rates, enforce calorie floors, warn on underweight loss goals, and use reference weight for protein when appropriate.

## 12. Menu optimizer

The menu optimizer is deterministic after food selection.

### Candidate composition

Meal templates define sensible role combinations:

```text
breakfast: breakfast protein + breakfast carbohydrate + fruit
lunch:     protein + carbohydrate + vegetable + cooking fat
dinner:    protein + vegetable + vegetable + cooking fat
snack:     snack protein + fruit, or another compatible combination
```

Food selection penalizes repeated use, increasing diversity across a 12-menu set.

### Portion optimization

For chosen foods, the optimizer builds a nutrient matrix where each column represents nutrients per gram of one food.

SciPy `lsq_linear` minimizes a weighted objective:

```text
calorie error
+ protein energy error
+ carbohydrate energy error
+ fat energy error
+ meal distribution error
+ portion regularization
```

Bounds enforce each food’s realistic minimum and maximum grams.

Results are rounded to practical increments, then one or more flexible ingredients absorb the remaining calorie residual.

Tests verify that generated menus remain within one percent of the requested calories and that snack options stay within five kcal.

## 13. Pantry-to-recipe matching

Recipe ingredients and pantry names are converted to normalized token sets.

Examples:

```text
eggs           ↔ Egg
chicken        ↔ Chicken Breast
fresh spinach  ↔ Spinach
```

For each recipe the service computes:

- ingredients available,
- ingredients missing,
- pantry coverage ratio,
- expiring ingredients used.

Suggestions sort by expiring-food usage first, then pantry coverage.

## 14. API caching

TheMealDB responses are cached by request URL in SQLite.

Read behavior:

1. return fresh cached body when available,
2. otherwise request the API,
3. cache successful JSON,
4. if the request fails, return stale cache when available,
5. otherwise raise `RecipeAPIError`.

This gives useful offline degradation without silently inventing recipes.

## 15. Streamlit client

The web client stores its `AgentApp` and selected conversation ID in Streamlit session state.

It reads structured domain data directly for dashboards and tables. These views do not call the LLM:

- daily macro cards,
- diary,
- pantry,
- expiry alerts,
- saved menus.

Only chat requests invoke the graph.

The client shows an animated thinking state after submission and records model steps taking more than ten seconds.

## 16. Rich CLI

The CLI streams graph updates and renders:

- model tool calls,
- shortened tool results,
- assistant Markdown,
- repair notices,
- friendly errors.

Direct slash commands bypass the model for fast structured views.

## 17. Testing strategy

The test suite follows the architecture:

### Pure unit tests

- nutrition formulas,
- unit conversion,
- ingredient matching,
- target resolution.

### Repository tests

- migrations,
- constraints,
- idempotency,
- update behavior,
- history preservation.

### Domain tests

- menu optimization,
- allergy enforcement,
- pantry ranking,
- shopping-list generation,
- progress trends.

### Tool tests

- Pydantic validation,
- structured JSON,
- English and Georgian inputs,
- domain-error propagation.

### Graph tests

A scripted fake chat model tests:

- tool loop,
- tool error recovery,
- malformed tool-call repair,
- dangling-call patching,
- provider fallback.

No API key is required for the normal suite.

## 18. Why this is an agent

This project is more than a prompt wrapper because the model:

- observes current application state,
- selects tools dynamically,
- generates structured arguments,
- receives tool observations,
- repairs failed actions,
- performs multi-step workflows,
- persists thread state,
- stops when a final response is ready.

At the same time, the model is not allowed to replace deterministic software where correctness matters.

That division of labor is the core architecture of ქონდაქარი.
