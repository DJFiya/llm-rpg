"""The structured-output helper must validate and repair JSON."""

from __future__ import annotations

import pytest
from pydantic import BaseModel

from llm_rpg.llm.base import LLMError, LLMProvider


class _Demo(BaseModel):
    name: str
    value: int


class _ScriptedProvider(LLMProvider):
    """Returns queued responses in order; used to simulate repair."""

    name = "scripted"

    def __init__(self, responses: list[str]) -> None:
        self._responses = list(responses)
        self.calls = 0

    def complete(self, system: str, user: str, *, json_mode: bool = False) -> str:
        self.calls += 1
        return self._responses.pop(0)


def test_parses_clean_json():
    p = _ScriptedProvider(['{"name": "ok", "value": 3}'])
    result = p.generate_json("sys", "user", _Demo, retries=2)
    assert result.name == "ok" and result.value == 3


def test_strips_markdown_fences():
    p = _ScriptedProvider(['```json\n{"name": "x", "value": 1}\n```'])
    result = p.generate_json("sys", "user", _Demo, retries=2)
    assert result.value == 1


def test_repairs_after_invalid_then_valid():
    p = _ScriptedProvider(["not json at all", '{"name": "y", "value": 2}'])
    result = p.generate_json("sys", "user", _Demo, retries=2)
    assert result.value == 2
    assert p.calls == 2


def test_raises_after_exhausting_retries():
    p = _ScriptedProvider(["nope", "still nope"])
    with pytest.raises(LLMError):
        p.generate_json("sys", "user", _Demo, retries=1)
