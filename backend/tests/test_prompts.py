"""提示词加载:按 (mtime, size) 缓存,文件修改后无需重启即可生效。"""

from __future__ import annotations

import app.prompts as prompts


def test_load_prompt_picks_up_edits_without_restart(tmp_path, monkeypatch):
    monkeypatch.setattr(prompts, "PROMPT_DIR", tmp_path)
    path = tmp_path / "demo.md"
    path.write_text("v1 $topic", encoding="utf-8")
    assert prompts.load_prompt("demo") == "v1 $topic"

    path.write_text("v2 $topic!", encoding="utf-8")
    assert prompts.load_prompt("demo") == "v2 $topic!"


def test_render_prompt_substitutes_placeholders(tmp_path, monkeypatch):
    monkeypatch.setattr(prompts, "PROMPT_DIR", tmp_path)
    (tmp_path / "tpl.md").write_text("方向:$topic", encoding="utf-8")
    assert prompts.render_prompt("tpl", topic="AI") == "方向:AI"
