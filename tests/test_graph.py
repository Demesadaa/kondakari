from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.tools import tool
from langgraph.checkpoint.memory import InMemorySaver

from agent.graph import build_graph, patch_dangling_tool_calls


class ScriptedModel(GenericFakeChatModel):
    """Replays pre-written AIMessages; bind_tools is a no-op so the graph can be tested offline."""

    def bind_tools(self, tools, **kwargs):
        return self


@tool
def divide(a: float, b: float) -> str:
    """Divide a by b."""
    return str(a / b)


def run(script, prompt="hi", thread="t1"):
    graph = build_graph(ScriptedModel(messages=iter(script)), [divide], lambda: "system", InMemorySaver())
    config = {"configurable": {"thread_id": thread}}
    return graph.invoke({"messages": [HumanMessage(prompt)]}, config)["messages"]


def call(name, args, call_id="c1"):
    return AIMessage(content="", tool_calls=[{"name": name, "args": args, "id": call_id}])


def test_tool_loop():
    messages = run([call("divide", {"a": 84, "b": 2}), AIMessage(content="It's 42.")])
    tool_msg = next(m for m in messages if isinstance(m, ToolMessage))
    assert tool_msg.content == "42.0"
    assert messages[-1].content == "It's 42."


def test_tool_error_is_fed_back_not_raised():
    messages = run([call("divide", {"a": 1, "b": 0}), AIMessage(content="Can't divide by zero.")])
    tool_msg = next(m for m in messages if isinstance(m, ToolMessage))
    assert tool_msg.status == "error" and "Tool error" in tool_msg.content
    assert messages[-1].content == "Can't divide by zero."


def test_invalid_tool_call_triggers_repair():
    broken = AIMessage(
        content="", invalid_tool_calls=[{"name": "divide", "args": "{bad json", "id": "x", "error": "JSON"}]
    )
    messages = run([broken, AIMessage(content="Recovered.")])
    assert any("could not be parsed" in m.content for m in messages if isinstance(m, HumanMessage))
    assert messages[-1].content == "Recovered."


def test_patch_dangling_tool_calls():
    history = [HumanMessage("x"), call("divide", {"a": 1, "b": 1})]
    patched = patch_dangling_tool_calls(history)
    assert isinstance(patched[-1], ToolMessage) and patched[-1].tool_call_id == "c1"


def test_provider_failure_uses_fallback_model():
    primary = ScriptedModel(messages=iter([]))
    fallback = ScriptedModel(messages=iter([AIMessage(content="Fallback answered.")]))
    graph = build_graph(
        primary,
        [divide],
        lambda: "system",
        InMemorySaver(),
        fallback_llms=[fallback],
    )
    messages = graph.invoke(
        {"messages": [HumanMessage("hello")]},
        {"configurable": {"thread_id": "fallback"}},
    )["messages"]
    assert messages[-1].content == "Fallback answered."
