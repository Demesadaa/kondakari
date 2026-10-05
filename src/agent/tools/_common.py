import json
from typing import Any

from pydantic_core import to_jsonable_python


def dump(data: Any) -> str:
    """Tool results are JSON so the model gets structured, unambiguous data."""
    return json.dumps(to_jsonable_python(data), ensure_ascii=False)
