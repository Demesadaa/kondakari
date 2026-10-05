def _key_hint(text: str) -> str:
    for marker, var in (("gemini", "GOOGLE_API_KEY=..."), ("google", "GOOGLE_API_KEY=..."),
                        ("openai", "OPENAI_API_KEY=..."), ("anthropic", "ANTHROPIC_API_KEY=..."),
                        ("groq", "GROQ_API_KEY=...")):
        if marker in text:
            return var
    return "e.g. GOOGLE_API_KEY=... or OPENAI_API_KEY=..."


def describe_error(error: Exception) -> str:
    """Turn provider/network exceptions into an actionable one-line message for the user."""
    # OpenAI/Anthropic/Groq expose status_code; Google's SDK uses an integer `code`.
    status = getattr(error, "status_code", None)
    if not isinstance(status, int) and isinstance(getattr(error, "code", None), int):
        status = error.code
    text = str(error).lower()
    name = type(error).__name__

    if "api key required" in text or "missing credentials" in text or "api_key client option must be set" in text:
        return ("No API key found for the selected model. Put it in .env "
                f"({_key_hint(text)}), save the file and start again.")
    if "insufficient_quota" in text or "credit_balance" in text or "billing" in text and status in (402, 429):
        return ("Your LLM account has no credits left. Add credits "
                "(OpenAI: https://platform.openai.com/settings/organization/billing) or switch LLM_MODEL in .env.")
    if "resource_exhausted" in text or status == 429 and "quota" in text:
        return "Free-tier quota reached. Wait a minute (per-minute limit) or until tomorrow (daily limit)."
    if "api key not valid" in text or "api_key_invalid" in text:
        return "The API key was rejected. Check the key in .env (no quotes or spaces) and restart."
    if status == 401 or "invalid api key" in text or "incorrect api key" in text:
        return "The API key was rejected. Check the key in .env (no quotes or spaces) and restart."
    if status == 403:
        return "The API key is not allowed to use this model. Pick another LLM_MODEL in .env."
    if status == 404 or "model_not_found" in text:
        return "Model not found. Check LLM_MODEL in .env (format provider:model, e.g. openai:gpt-4o-mini)."
    if status == 429:
        return "Rate limited by the LLM provider. Wait a few seconds and try again."
    if isinstance(status, int) and status >= 500:
        return "The LLM provider is having problems right now. Try again shortly."
    if "connection" in name.lower() or "timeout" in name.lower() or isinstance(error, (ConnectionError, TimeoutError)):
        return "Could not reach the LLM provider. Check your internet connection."
    return f"Unexpected error ({name}): {error}"
