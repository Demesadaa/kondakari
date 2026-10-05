"""Streamlit client for ქონდაქარი.

The web layer is intentionally thin: it reads from the same repositories and invokes the
same LangGraph used by the Rich CLI.
"""

from __future__ import annotations

import html
import logging
from datetime import date, timedelta
from pathlib import Path

import streamlit as st
from langchain_core.messages import AIMessage, HumanMessage
from langgraph.errors import GraphRecursionError

from agent.app import AgentApp, create_app
from agent.config import get_settings
from agent.errors import describe_error
from agent.kitchen import EXPIRING_DAYS

AGENT_NAME = "ქონდაქარი"
ASSET_DIR = Path(__file__).parent / "assets"
LOGO_PATH = ASSET_DIR / "kondakari.png"
STYLE_PATH = ASSET_DIR / "style.css"

NAV_ITEMS = {
    "Home": "⌂",
    "Chat": "✦",
    "Pantry": "◫",
    "Menus": "≡",
}


def _safe(value: object) -> str:
    return html.escape(str(value))


def _message_text(message: AIMessage | HumanMessage) -> str:
    text = getattr(message, "text", None)
    if isinstance(text, str):
        return text
    if isinstance(message.content, str):
        return message.content
    return "\n".join(
        str(block.get("text", "")) if isinstance(block, dict) else str(block)
        for block in message.content
    ).strip()


def _configure() -> None:
    st.set_page_config(
        page_title=f"{AGENT_NAME} · Kitchen & nutrition",
        page_icon=str(LOGO_PATH),
        layout="wide",
        initial_sidebar_state="expanded",
    )
    st.markdown(f"<style>{STYLE_PATH.read_text(encoding='utf-8')}</style>", unsafe_allow_html=True)


def _get_app() -> AgentApp:
    if "agent_app" not in st.session_state:
        settings = get_settings()
        settings.data_dir.mkdir(parents=True, exist_ok=True)
        logging.basicConfig(
            filename=settings.log_path,
            encoding="utf-8",
            level=settings.log_level.upper(),
            format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        )
        logging.captureWarnings(True)
        st.session_state.agent_app = create_app(settings)
    return st.session_state.agent_app


def _ensure_thread(app: AgentApp) -> str:
    if "thread_id" not in st.session_state or app.threads.get(st.session_state.thread_id) is None:
        st.session_state.thread_id = app.threads.create().id
    return st.session_state.thread_id


def _sidebar(app: AgentApp) -> str:
    with st.sidebar:
        st.image(str(LOGO_PATH), width=112)
        st.markdown(
            '<div class="brand-name">ქონდაქარი</div>'
            '<div class="brand-subtitle">Kitchen · Nutrition · Wellbeing</div>',
            unsafe_allow_html=True,
        )

        page = st.radio(
            "Navigation",
            list(NAV_ITEMS),
            format_func=lambda name: f"{NAV_ITEMS[name]}  {name}",
            label_visibility="collapsed",
            key="page",
        )

        st.markdown("---")
        thread_id = _ensure_thread(app)
        recent = app.threads.list_recent()
        ids = [thread.id for thread in recent]
        if thread_id not in ids:
            ids.insert(0, thread_id)

        selected = st.selectbox(
            "Conversation",
            ids,
            index=ids.index(thread_id),
            format_func=lambda value: (
                app.threads.get(value).title if app.threads.get(value) else value
            ),
        )
        if selected != thread_id:
            st.session_state.thread_id = selected
            st.rerun()

        if st.button("＋  New conversation", width="stretch"):
            st.session_state.thread_id = app.threads.create().id
            st.rerun()

        targets = app.coach.try_targets()
        st.markdown("---")
        if targets:
            st.caption("DAILY TARGET")
            st.markdown(f"**{targets.kcal:,} kcal**")
            st.caption(
                f"Protein {targets.protein_g}g · Carbs {targets.carbs_g}g · Fat {targets.fat_g}g"
            )
        else:
            st.caption("Complete your body profile in chat to calculate a daily target.")
        st.caption(f"Model · {app.settings.llm_model}")
    return page


def _page_header(kicker: str, title: str, description: str) -> None:
    st.markdown(f'<div class="eyebrow">{_safe(kicker)}</div>', unsafe_allow_html=True)
    st.markdown(f"# {title}")
    st.markdown(f'<div class="lead">{_safe(description)}</div>', unsafe_allow_html=True)


def _metric(label: str, value: str, note: str = "") -> None:
    st.markdown(
        '<div class="metric-card">'
        f'<div class="metric-label">{_safe(label)}</div>'
        f'<div class="metric-value">{_safe(value)}</div>'
        f'<div class="metric-note">{_safe(note)}</div>'
        "</div>",
        unsafe_allow_html=True,
    )


def _navigate(page: str) -> None:
    st.session_state.page = page


def _home(app: AgentApp) -> None:
    hero_text, hero_logo = st.columns([1.8, 0.7], vertical_alignment="center")
    with hero_text:
        _page_header(
            "Your table, thoughtfully planned",
            "Eat well. Train well.\nLive steadily.",
            "ქონდაქარი brings your pantry, daily nutrition, meal planning, and progress "
            "into one calm place—in English or Georgian.",
        )
        st.button(
            "Talk to ქონდაქარი",
            type="primary",
            on_click=_navigate,
            args=("Chat",),
        )
    with hero_logo:
        st.image(str(LOGO_PATH), width="stretch")

    summary = app.coach.daily_summary(date.today())
    consumed = summary["consumed"]
    targets = summary.get("targets")
    pantry = app.kitchen.pantry.search()
    expiring = [item for item in pantry if item.days_left is not None and item.days_left <= EXPIRING_DAYS]
    workouts = summary["workouts"]

    st.markdown('<div class="section-kicker">Today at a glance</div>', unsafe_allow_html=True)
    cols = st.columns(4)
    with cols[0]:
        _metric(
            "Energy",
            f"{consumed.kcal:,.0f} kcal",
            f"of {targets['kcal']:,} kcal" if targets else "Set up your profile",
        )
    with cols[1]:
        _metric(
            "Protein",
            f"{consumed.protein:.0f} g",
            f"{max(targets['protein'] - consumed.protein, 0):.0f} g remaining"
            if targets
            else "No target yet",
        )
    with cols[2]:
        _metric("Pantry", str(len(pantry)), f"{len(expiring)} need attention")
    with cols[3]:
        _metric(
            "Movement",
            f"{sum(w['minutes'] for w in workouts):.0f} min" if workouts else "—",
            f"{len(workouts)} workout{'s' if len(workouts) != 1 else ''} today",
        )

    if targets:
        st.markdown('<div class="section-kicker">Daily balance</div>', unsafe_allow_html=True)
        macro_cols = st.columns(3)
        for col, label, used, target in (
            (macro_cols[0], "Protein", consumed.protein, targets["protein"]),
            (macro_cols[1], "Carbohydrates", consumed.carbs, targets["carbs"]),
            (macro_cols[2], "Fat", consumed.fat, targets["fat"]),
        ):
            pct = min(used / target * 100, 100) if target else 0
            with col:
                st.markdown(
                    '<div class="welcome-card">'
                    f"<strong>{_safe(label)}</strong><br>"
                    f'<span class="row-muted">{used:.0f} of {target:.0f} g</span>'
                    '<div class="macro-track">'
                    f'<div class="macro-fill" style="width:{pct:.1f}%"></div>'
                    "</div></div>",
                    unsafe_allow_html=True,
                )

    left, right = st.columns([1.25, 0.75])
    with left:
        st.markdown('<div class="section-kicker">Food diary</div>', unsafe_allow_html=True)
        if summary["entries"]:
            for entry in summary["entries"][-7:]:
                st.markdown(
                    '<div class="food-row">'
                    f'<span class="meal-name">{_safe(entry["meal"])}</span>'
                    f"<strong>{_safe(entry['food'])}</strong>"
                    f'<span class="row-muted">{entry["grams"]:g} g</span>'
                    f'<span class="row-muted">{entry["kcal"]} kcal</span>'
                    "</div>",
                    unsafe_allow_html=True,
                )
        else:
            st.markdown(
                '<div class="empty-card">Nothing logged today.<br>'
                '<span class="row-muted">Tell ქონდაქარი what you ate.</span></div>',
                unsafe_allow_html=True,
            )
    with right:
        st.markdown('<div class="section-kicker">Use soon</div>', unsafe_allow_html=True)
        if expiring:
            for item in expiring[:5]:
                expiry = "expired" if item.days_left < 0 else f"{item.days_left}d left"
                st.markdown(
                    '<div class="pantry-row" style="grid-template-columns:1fr auto">'
                    f"<strong>{_safe(item.name)}</strong>"
                    f'<span class="expiry-soon">{_safe(expiry)}</span>'
                    "</div>",
                    unsafe_allow_html=True,
                )
        else:
            st.markdown(
                '<div class="empty-card">Nothing is expiring soon.</div>',
                unsafe_allow_html=True,
            )


def _thread_messages(app: AgentApp, thread_id: str) -> list[HumanMessage | AIMessage]:
    snapshot = app.graph.get_state(app.config_for(thread_id))
    messages = snapshot.values.get("messages", []) if snapshot.values else []
    return [
        message
        for message in messages
        if isinstance(message, (HumanMessage, AIMessage)) and _message_text(message)
    ]


def _chat(app: AgentApp) -> None:
    _page_header(
        "A seat at the kitchen table",
        "Talk to ქონდაქარი",
        "Ask about calories, macros, workouts, recipes, your pantry, or a complete menu. "
        "Write naturally in English or Georgian.",
    )
    thread_id = _ensure_thread(app)
    messages = _thread_messages(app, thread_id)
    if not messages:
        st.markdown(
            '<div class="welcome-card"><strong>Try one of these:</strong><br><br>'
            '“Build me a 2,100 kcal menu with no pork.”<br>'
            '“I ate 5 khinkali for lunch—log it.”<br>'
            '„დღეს რა მოვამზადო ჩემი პროდუქტებით?“</div>',
            unsafe_allow_html=True,
        )

    for message in messages:
        role = "user" if isinstance(message, HumanMessage) else "assistant"
        avatar = "👤" if role == "user" else str(LOGO_PATH)
        with st.chat_message(role, avatar=avatar):
            st.markdown(_message_text(message))

    prompt = st.chat_input("Ask ქონდაქარი… / ჰკითხე ქონდაქარს…")
    if not prompt:
        return

    app.threads.touch(thread_id, first_message=prompt)
    with st.chat_message("user", avatar="👤"):
        st.markdown(prompt)

    try:
        with st.chat_message("assistant", avatar=str(LOGO_PATH)):
            with st.spinner("ქონდაქარი is preparing your answer…", show_time=True):
                result = app.graph.invoke(
                    {"messages": [HumanMessage(prompt)]},
                    app.config_for(thread_id),
                )
            response = next(
                (
                    message
                    for message in reversed(result["messages"])
                    if isinstance(message, AIMessage) and _message_text(message)
                ),
                None,
            )
            if response:
                st.markdown(_message_text(response))
            else:
                st.warning("The agent finished without a text response. Please rephrase your request.")
    except GraphRecursionError:
        st.warning(
            f"The request stopped after {app.settings.max_agent_steps} steps. "
            "Try a more specific request."
        )
    except Exception as error:
        logging.getLogger("agent.web").exception("Turn failed")
        st.error(describe_error(error))


def _pantry(app: AgentApp) -> None:
    _page_header(
        "Know what you have",
        "Your pantry",
        "Ingredients are ordered by expiry so the food that needs attention appears first.",
    )
    items = app.kitchen.pantry.search()
    if not items:
        st.markdown(
            '<div class="empty-card">Your pantry is empty.<br>'
            '<span class="row-muted">Add food naturally in Chat—for example, “I bought six eggs.”</span></div>',
            unsafe_allow_html=True,
        )
        return

    filters = st.columns([1.4, 1, 1])
    query = filters[0].text_input("Search", placeholder="Ingredient name")
    location = filters[1].selectbox("Location", ["all", "fridge", "freezer", "pantry"])
    expiry_filter = filters[2].selectbox("Expiry", ["all", "next 3 days", "next 7 days", "expired"])

    filtered = items
    if query:
        filtered = [item for item in filtered if query.lower() in item.name.lower()]
    if location != "all":
        filtered = [item for item in filtered if item.location == location]
    if expiry_filter == "next 3 days":
        filtered = [item for item in filtered if item.days_left is not None and 0 <= item.days_left <= 3]
    elif expiry_filter == "next 7 days":
        filtered = [item for item in filtered if item.days_left is not None and 0 <= item.days_left <= 7]
    elif expiry_filter == "expired":
        filtered = [item for item in filtered if item.days_left is not None and item.days_left < 0]

    st.markdown(f'<div class="section-kicker">{len(filtered)} ingredients</div>', unsafe_allow_html=True)
    for item in filtered:
        if item.days_left is None:
            expiry, css = "No expiry", "row-muted"
        elif item.days_left < 0:
            expiry, css = f"Expired {abs(item.days_left)}d ago", "expiry-soon"
        elif item.days_left <= EXPIRING_DAYS:
            expiry, css = f"{item.days_left}d left", "expiry-soon"
        else:
            expiry, css = str(item.expires_on), "row-muted"
        st.markdown(
            '<div class="pantry-row">'
            f"<strong>{_safe(item.name)}</strong>"
            f"<span>{item.quantity:g} {_safe(item.unit)}</span>"
            f'<span class="row-muted">{_safe(item.location)}</span>'
            f'<span class="{css}">{_safe(expiry)}</span>'
            "</div>",
            unsafe_allow_html=True,
        )


def _menus(app: AgentApp) -> None:
    _page_header(
        "Measured, varied, practical",
        "Generated menus",
        "Every set is built to your calorie and macro targets with portion sizes you can actually use.",
    )
    menu_set = app.coach.menus.get()
    if menu_set is None:
        st.markdown(
            '<div class="empty-card">No menu set yet.<br>'
            '<span class="row-muted">Ask in Chat: “Create 7 different 2,000 kcal menus.”</span></div>',
            unsafe_allow_html=True,
        )
        return

    target = menu_set.target
    top = st.columns(4)
    for col, label, value in (
        (top[0], "Calories", f"{target.kcal:,.0f}"),
        (top[1], "Protein", f"{target.protein:.0f} g"),
        (top[2], "Carbs", f"{target.carbs:.0f} g"),
        (top[3], "Fat", f"{target.fat:.0f} g"),
    ):
        with col:
            _metric(label, value, menu_set.diet.title() if label == "Calories" else "daily target")

    st.markdown('<div class="section-kicker">Daily options</div>', unsafe_allow_html=True)
    for menu in menu_set.menus:
        totals = menu.totals
        with st.expander(
            f"Menu {menu.number}  ·  {totals.kcal:.0f} kcal  ·  "
            f"P {totals.protein:.0f} / C {totals.carbs:.0f} / F {totals.fat:.0f}",
            expanded=menu.number == 1,
        ):
            meal_columns = st.columns(min(len(menu.meals), 4))
            for index, meal in enumerate(menu.meals):
                with meal_columns[index % len(meal_columns)]:
                    st.markdown(f'<div class="meal-name">{_safe(meal.meal)}</div>', unsafe_allow_html=True)
                    for item in meal.items:
                        local_name = f" · {item.food_ka}" if item.food_ka else ""
                        st.markdown(
                            f"**{_safe(item.food)}**  \n"
                            f"<span class='row-muted'>{_safe(local_name)} · {item.grams:g} g · "
                            f"{item.macros.kcal:.0f} kcal</span>",
                            unsafe_allow_html=True,
                        )


def main() -> None:
    _configure()
    try:
        app = _get_app()
    except Exception as error:
        logging.getLogger("agent.web").exception("Startup failed")
        st.image(str(LOGO_PATH), width=110)
        st.error(describe_error(error))
        st.info("Check `.env`, save it, and refresh this page.")
        return

    page = _sidebar(app)
    if page == "Home":
        _home(app)
    elif page == "Chat":
        _chat(app)
    elif page == "Pantry":
        _pantry(app)
    else:
        _menus(app)


if __name__ == "__main__":
    main()
