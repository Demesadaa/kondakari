import pytest

from agent.errors import describe_error


class FakeAPIError(Exception):
    def __init__(self, message: str, status_code: int) -> None:
        super().__init__(message)
        self.status_code = status_code


@pytest.mark.parametrize(("error", "expected"), [
    (FakeAPIError("Error code: 429 - {'type': 'insufficient_quota', 'code': 'credit_balance_exhausted'}", 429), "no credits"),
    (FakeAPIError("Incorrect API key provided", 401), "rejected"),
    (FakeAPIError("The model `gpt-9` does not exist", 404), "Model not found"),
    (FakeAPIError("Rate limit reached for requests", 429), "Rate limited"),
    (FakeAPIError("429 RESOURCE_EXHAUSTED. You exceeded your current quota", 429), "Free-tier quota"),
    (FakeAPIError("400 INVALID_ARGUMENT. API key not valid. Please pass a valid API key.", 400), "rejected"),
    (FakeAPIError("Bad gateway", 502), "having problems"),
    (ValueError("API key required for Gemini Developer API. Set GOOGLE_API_KEY"), "GOOGLE_API_KEY=..."),
    (ValueError("Missing credentials. Please set the `OPENAI_API_KEY` environment variable."), "OPENAI_API_KEY=..."),
    (ConnectionError("refused"), "internet"),
    (RuntimeError("boom"), "Unexpected error (RuntimeError)"),
])
def test_describe_error(error, expected):
    assert expected in describe_error(error)
