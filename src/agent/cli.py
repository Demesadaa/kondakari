import json
import logging
import sys
from datetime import date, timedelta

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langgraph.errors import GraphRecursionError
from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.table import Table

from agent.app import AgentApp, create_app
from agent.config import get_settings
from agent.errors import describe_error
from agent.kitchen import EXPIRING_DAYS

AGENT_NAME = "ქონდაქარი"

console = Console()
log = logging.getLogger("agent")

HELP = """[bold]Commands[/bold]
  /today           today's food diary vs targets
  /profile         body profile and daily targets
  /menus [id]      show generated menus (latest set by default)
  /pantry          show the pantry
  /plan            show the next 7 days of meals
  /shopping        show the shopping list
  /new             start a new conversation
  /threads         list recent conversations
  /switch <id>     resume a conversation
  /help            show this help
  /quit            exit

[bold]Try[/bold]  "I'm 29, male, 182 cm, 88 kg, office job, gym 3x a week. I want to lose weight."
     "Make me 12 different menus of exactly 2100 kcal, no pork"
     "ლანჩზე 5 ხინკალი და პომიდვრის სალათი ვჭამე"  ·  "რა მოვამზადო დღეს?"
     "I bought 6 eggs, spinach expiring Friday and 500g chicken breast\""""


def _shorten(text: str, limit: int = 200) -> str:
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


def render(node: str, message) -> None:
    if isinstance(message, AIMessage):
        for call in message.tool_calls:
            console.print(f"  [dim]→ {call['name']}({_shorten(json.dumps(call['args']), 120)})[/dim]")
        if message.text:
            console.print(Panel(Markdown(message.text), title=AGENT_NAME, title_align="left", border_style="green"))
    elif isinstance(message, ToolMessage):
        style = "red" if message.status == "error" else "dim"
        console.print(f"  [{style}]← {message.name}: {_shorten(message.text)}[/{style}]")
    elif node == "repair":
        console.print("  [yellow]↻ malformed tool call, asking the model to retry[/yellow]")


def run_turn(app: AgentApp, thread_id: str, user_input: str) -> None:
    try:
        with console.status("[dim]thinking…[/dim]", spinner="dots"):
            stream = app.graph.stream(
                {"messages": [HumanMessage(user_input)]}, app.config_for(thread_id), stream_mode="updates"
            )
            for update in stream:
                for node, payload in update.items():
                    for message in (payload or {}).get("messages", []):
                        render(node, message)
    except GraphRecursionError:
        console.print(f"[yellow]Stopped after {app.settings.max_agent_steps} steps. Try a more specific request.[/yellow]")
    except KeyboardInterrupt:
        console.print("[yellow]Interrupted.[/yellow]")
    except Exception as e:
        log.exception("Turn failed")
        console.print(f"[red]✗ {describe_error(e)}[/red]\n[dim]Full details: {app.settings.log_path}[/dim]")


def show_pantry(app: AgentApp) -> None:
    items = app.kitchen.pantry.search()
    if not items:
        console.print("[dim]Pantry is empty.[/dim]")
        return
    table = Table("id", "item", "qty", "where", "expires", title="Pantry")
    for i in items:
        if i.days_left is None:
            expiry = "[dim]—[/dim]"
        elif i.days_left < 0:
            expiry = f"[bold red]{i.expires_on} (expired)[/bold red]"
        elif i.days_left <= EXPIRING_DAYS:
            expiry = f"[yellow]{i.expires_on} ({i.days_left}d)[/yellow]"
        else:
            expiry = f"{i.expires_on} ({i.days_left}d)"
        table.add_row(str(i.id), i.name, f"{i.quantity:g} {i.unit}", i.location, expiry)
    console.print(table)


def show_plan(app: AgentApp) -> None:
    today = date.today()
    entries = app.kitchen.recipes.plan_between(today, today + timedelta(days=6))
    if not entries:
        console.print("[dim]Nothing planned for the next 7 days.[/dim]")
        return
    table = Table("day", "meal", "recipe", title="Meal plan")
    for e in entries:
        table.add_row(e.day.strftime("%a %d %b"), e.meal, e.recipe_name)
    console.print(table)


def show_shopping(app: AgentApp) -> None:
    items = app.kitchen.shopping.items()
    if not items:
        console.print("[dim]Shopping list is empty.[/dim]")
        return
    table = Table("id", "item", "for", title="Shopping list")
    for i in items:
        table.add_row(str(i.id), i.name, i.detail)
    console.print(table)


def _macro_line(kcal: float, protein: float, carbs: float, fat: float) -> str:
    return f"{kcal:.0f} kcal · P {protein:.0f} g · C {carbs:.0f} g · F {fat:.0f} g"


def show_today(app: AgentApp) -> None:
    summary = app.coach.daily_summary(date.today())
    table = Table("id", "meal", "food", "g", "kcal", title=f"Food diary · {summary['day']}")
    for e in summary["entries"]:
        table.add_row(str(e["id"]), e["meal"], e["food"], f"{e['grams']:g}", str(e["kcal"]))
    c = summary["consumed"]
    lines = [f"Eaten:     {_macro_line(c.kcal, c.protein, c.carbs, c.fat)}"]
    if t := summary.get("targets"):
        r = summary["remaining"]
        lines.append(f"Target:    {_macro_line(t['kcal'], t['protein'], t['carbs'], t['fat'])}")
        color = "green" if r["kcal"] >= 0 else "red"
        lines.append(f"Remaining: [{color}]{_macro_line(r['kcal'], r['protein'], r['carbs'], r['fat'])}[/{color}]")
    else:
        lines.append(f"[dim]{summary['hint']}[/dim]")
    if summary["workouts"]:
        lines.append(f"Workouts:  {', '.join(w['activity'] for w in summary['workouts'])} (~{summary['burned_kcal']} kcal)")
    if summary["entries"]:
        console.print(table)
    console.print(Panel("\n".join(lines), border_style="cyan"))


def show_profile(app: AgentApp) -> None:
    profile = app.coach.profile.get()
    weight = app.coach.current_weight()
    table = Table("field", "value", title="Body profile", show_header=False)
    for key, value in [("sex", profile.sex), ("age", profile.age), ("height", profile.height_cm and f"{profile.height_cm:g} cm"),
                       ("weight", weight and f"{weight:g} kg"), ("activity", profile.activity), ("goal", profile.goal),
                       ("rate", profile.weekly_rate_kg and f"{profile.weekly_rate_kg:g} kg/week"),
                       ("target weight", profile.target_weight_kg and f"{profile.target_weight_kg:g} kg")]:
        table.add_row(key, str(value) if value is not None else "[dim]—[/dim]")
    console.print(table)
    if targets := app.coach.try_targets():
        body = (f"BMI {targets.bmi} · BMR {targets.bmr} · TDEE {targets.tdee}\n"
                f"[bold]{_macro_line(targets.kcal, targets.protein_g, targets.carbs_g, targets.fat_g)}[/bold]")
        body += "".join(f"\n[yellow]⚠ {w}[/yellow]" for w in targets.warnings)
        console.print(Panel(body, title="Daily targets", border_style="green"))
    else:
        console.print(f"[dim]{app.coach.setup_hint()}[/dim]")


def show_menus(app: AgentApp, arg: str) -> None:
    set_id = int(arg) if arg.strip().isdigit() else None
    menu_set = app.coach.menus.get(set_id)
    if menu_set is None:
        console.print("[dim]No menus yet. Ask for e.g. '5 menus of 2000 kcal'.[/dim]")
        return
    t = menu_set.target
    console.print(f"[bold]Menu set #{menu_set.id}[/bold] · {menu_set.diet} · target {_macro_line(t.kcal, t.protein, t.carbs, t.fat)}")
    for menu in menu_set.menus:
        table = Table("meal", "food", "ქართულად", "g", "kcal", "P", "C", "F", title=f"Menu {menu.number}")
        for meal in menu.meals:
            for i, item in enumerate(meal.items):
                m = item.macros
                table.add_row(meal.meal if i == 0 else "", item.food, item.food_ka, f"{item.grams:g}",
                              f"{m.kcal:.0f}", f"{m.protein:.0f}", f"{m.carbs:.0f}", f"{m.fat:.0f}")
            table.add_section()
        tot = menu.totals
        table.add_row("[bold]total[/bold]", "", "", "", f"[bold]{tot.kcal:.0f}[/bold]",
                      f"{tot.protein:.0f}", f"{tot.carbs:.0f}", f"{tot.fat:.0f}")
        console.print(table)


def show_threads(app: AgentApp, current: str) -> None:
    table = Table("id", "title", "updated", title="Conversations")
    for t in app.threads.list_recent():
        marker = " [green]●[/green]" if t.id == current else ""
        table.add_row(t.id + marker, t.title, t.updated_at)
    console.print(table)


def main() -> int:
    # Windows pipes/legacy consoles default to cp1252, which cannot encode Georgian.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")

    settings = get_settings()
    # Logs (including tracebacks) go to a file so they never clutter the chat.
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        filename=settings.log_path,
        encoding="utf-8",
        level=settings.log_level.upper(),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    logging.captureWarnings(True)

    try:
        app = create_app(settings)
    except Exception as e:
        log.exception("Startup failed")
        console.print(f"[red]Failed to start: {describe_error(e)}[/red]\nCheck your .env (see .env.example).")
        return 1

    thread = app.threads.create()
    console.print(
        Panel(
            f"Model: [bold]{settings.llm_model}[/bold]   Conversation: {thread.id}\nType /help for commands.",
            title=f"🌿 {AGENT_NAME} · kitchen & nutrition agent",
        )
    )

    try:
        while True:
            try:
                user_input = console.input("[bold cyan]you ›[/bold cyan] ").strip()
            except (EOFError, KeyboardInterrupt):
                break
            if not user_input:
                continue

            command, _, arg = user_input.partition(" ")
            match command:
                case "/quit" | "/exit":
                    break
                case "/help":
                    console.print(HELP)
                case "/today":
                    show_today(app)
                case "/profile":
                    show_profile(app)
                case "/menus":
                    show_menus(app, arg)
                case "/pantry":
                    show_pantry(app)
                case "/plan":
                    show_plan(app)
                case "/shopping":
                    show_shopping(app)
                case "/new":
                    thread = app.threads.create()
                    console.print(f"[green]New conversation {thread.id}[/green]")
                case "/threads":
                    show_threads(app, thread.id)
                case "/switch":
                    target = app.threads.get(arg.strip())
                    if target is None:
                        console.print("[red]Unknown conversation id. Use /threads.[/red]")
                    else:
                        thread = target
                        console.print(f"[green]Resumed '{thread.title}'[/green]")
                case _ if command.startswith("/"):
                    console.print("[red]Unknown command.[/red]\n" + HELP)
                case _:
                    app.threads.touch(thread.id, first_message=user_input)
                    run_turn(app, thread.id, user_input)
    finally:
        app.close()

    console.print("[dim]Bye.[/dim]")
    return 0
