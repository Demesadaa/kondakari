from langchain.chat_models import init_chat_model
from langchain_core.language_models import BaseChatModel

from agent.config import Settings

# These SDKs retry only transient failures (network, 5xx, rate limits honouring Retry-After) and skip
# permanent ones such as invalid keys or exhausted quota, which a blanket retry would repeat pointlessly.
_NATIVE_RETRY_PROVIDERS = {"openai", "anthropic", "groq", "google_genai"}


def build_llm(settings: Settings) -> BaseChatModel:
    """Provider-agnostic: switch providers by changing LLM_MODEL (e.g. 'anthropic:claude-sonnet-4-5')."""
    return build_model(settings.llm_model, settings)


def build_model(model_name: str, settings: Settings) -> BaseChatModel:
    provider = model_name.split(":", 1)[0]
    kwargs = (
        {
            "max_retries": settings.llm_max_retries,
            "timeout": settings.llm_timeout_seconds,
        }
        if provider in _NATIVE_RETRY_PROVIDERS
        else {}
    )
    if provider == "google_genai":
        kwargs["reasoning_effort"] = settings.llm_reasoning_effort
    return init_chat_model(model_name, temperature=settings.llm_temperature, **kwargs)


def build_fallback_llms(settings: Settings) -> list[BaseChatModel]:
    """Models attempted in order if the primary provider/model fails."""
    return [build_model(name, settings) for name in settings.fallback_model_names]
