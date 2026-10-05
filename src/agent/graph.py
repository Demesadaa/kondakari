import logging
import time
from collections.abc import Callable
from typing import Annotated, Literal, TypedDict

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, AnyMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.tools import BaseTool
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from langgraph.graph.state import CompiledStateGraph
from langgraph.prebuilt import ToolNode

log = logging.getLogger(__name__)


class AgentState(TypedDict):
    messages: Annotated[list[AnyMessage], add_messages]


def format_tool_error(error: Exception) -> str:
    log.warning("Tool error: %r", error)
    return f"Tool error: {error}. Check the arguments against the tool schema and try again."


def patch_dangling_tool_calls(messages: list[AnyMessage]) -> list[AnyMessage]:
    """Every tool call must be answered by a ToolMessage or providers reject the history.

    A turn interrupted mid-flight (Ctrl+C, step limit, crash) can leave unanswered calls in the checkpoint.
    """
    answered = {m.tool_call_id for m in messages if isinstance(m, ToolMessage)}
    patched: list[AnyMessage] = []
    for message in messages:
        patched.append(message)
        if isinstance(message, AIMessage):
            patched.extend(
                ToolMessage(content="Tool call was cancelled.", tool_call_id=call["id"], status="error")
                for call in message.tool_calls
                if call["id"] not in answered
            )
    return patched


def build_graph(
    llm: BaseChatModel,
    tools: list[BaseTool],
    system_prompt: Callable[[], str],
    checkpointer: BaseCheckpointSaver | None = None,
    fallback_llms: list[BaseChatModel] | None = None,
) -> CompiledStateGraph:
    """system_prompt is called on every model step so it can carry fresh context (date, stored data)."""
    model = llm.bind_tools(tools)
    if fallback_llms:
        model = model.with_fallbacks([fallback.bind_tools(tools) for fallback in fallback_llms])

    def agent(state: AgentState) -> dict:
        system = SystemMessage(system_prompt())
        started = time.perf_counter()
        try:
            response = model.invoke([system, *patch_dangling_tool_calls(state["messages"])])
        finally:
            elapsed = time.perf_counter() - started
            if elapsed >= 10:
                log.warning("Slow model step completed in %.2fs", elapsed)
            else:
                log.info("Model step completed in %.2fs", elapsed)
        return {"messages": [response]}

    def repair(state: AgentState) -> dict:
        last = state["messages"][-1]
        details = "; ".join(f"{c.get('name')}: {c.get('error')}" for c in last.invalid_tool_calls)
        log.warning("Malformed tool call(s): %s", details)
        return {
            "messages": [
                HumanMessage(
                    f"[system notice] Your previous tool call could not be parsed ({details}). "
                    "Retry with valid JSON arguments that match the tool schema."
                )
            ]
        }

    def route(state: AgentState) -> Literal["tools", "repair", "__end__"]:
        last = state["messages"][-1]
        if isinstance(last, AIMessage):
            if last.tool_calls:
                return "tools"
            if last.invalid_tool_calls:
                return "repair"
        return END

    graph = StateGraph(AgentState)
    graph.add_node("agent", agent)
    graph.add_node("tools", ToolNode(tools, handle_tool_errors=format_tool_error))
    graph.add_node("repair", repair)

    graph.add_edge(START, "agent")
    graph.add_conditional_edges("agent", route)
    graph.add_edge("tools", "agent")
    graph.add_edge("repair", "agent")

    return graph.compile(checkpointer=checkpointer)
