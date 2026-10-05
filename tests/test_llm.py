from agent.config import Settings
from agent import llm as llm_module


def test_google_model_gets_bounded_latency_settings(monkeypatch):
    captured = {}

    def fake_init(model_name, **kwargs):
        captured.update(model=model_name, **kwargs)
        return object()

    monkeypatch.setattr(llm_module, "init_chat_model", fake_init)
    settings = Settings(
        llm_model="google_genai:gemini-test",
        llm_max_retries=0,
        llm_timeout_seconds=25,
        llm_reasoning_effort="low",
    )
    llm_module.build_llm(settings)

    assert captured["model"] == "google_genai:gemini-test"
    assert captured["max_retries"] == 0
    assert captured["timeout"] == 25
    assert captured["reasoning_effort"] == "low"


def test_fallback_model_names_ignore_empty_entries():
    settings = Settings(llm_fallback_models=" first:model, ,second:model ")
    assert settings.fallback_model_names == ["first:model", "second:model"]
