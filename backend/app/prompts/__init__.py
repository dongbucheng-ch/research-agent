"""Prompt templates and a tiny $placeholder renderer."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from string import Template

PROMPT_DIR = Path(__file__).resolve().parent


@lru_cache(maxsize=64)
def _read_prompt(name: str, mtime: float, size: int) -> str:
    return (PROMPT_DIR / f"{name}.md").read_text(encoding="utf-8")


def load_prompt(name: str) -> str:
    """读取提示词;按 (mtime, size) 缓存,编辑 .md 后无需重启即可生效。"""
    path = PROMPT_DIR / f"{name}.md"
    stat = path.stat()
    return _read_prompt(name, stat.st_mtime, stat.st_size)


def render_prompt(name: str, **kwargs: object) -> str:
    return Template(load_prompt(name)).safe_substitute(**kwargs)
