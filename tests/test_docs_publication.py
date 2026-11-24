"""The user website must not discover repository engineering/agent material."""
import importlib.util
from pathlib import Path

import pytest


def builder(tmp_path, monkeypatch):
    path = Path(__file__).resolve().parents[1] / "tools/build_docs.py"
    spec = importlib.util.spec_from_file_location("docs_publication", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, "ROOT", tmp_path)
    monkeypatch.setattr(module, "STAGING", tmp_path / "work/docs-source")
    return module


def write(root, relative, content):
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def test_staging_keeps_downloads_without_publishing_engineering(tmp_path, monkeypatch):
    module = builder(tmp_path, monkeypatch)
    write(tmp_path, "docs/index.md", "[Model](../examples/sample/model.city.json)")
    asset = write(tmp_path, "examples/sample/model.city.json", '{"type":"CityJSON"}')
    for path in ("AGENTS.md", "README.md", ".agents/skills/private/SKILL.md",
                 "docs/engineering-notes.md", "examples/sample/README.md",
                 "data/private.json", "outputs/private.json"):
        write(tmp_path, path, "Engineering material outside the user manual")
    module.stage()
    staged = {p.relative_to(module.STAGING).as_posix()
              for p in module.STAGING.rglob("*") if p.is_file()}
    assert staged == {"index.md", "project/examples/sample/model.city.json"}
    assert (module.STAGING / "project/examples/sample/model.city.json").read_bytes() == asset.read_bytes()
    assert "project/examples/sample/model.city.json" in (module.STAGING / "index.md").read_text()


def test_user_page_cannot_pull_agent_instructions_into_the_site(tmp_path, monkeypatch):
    module = builder(tmp_path, monkeypatch)
    write(tmp_path, "AGENTS.md", "Private to the agent workflow")
    write(tmp_path, "docs/index.md", "[Agent instructions](../AGENTS.md)")
    with pytest.raises(ValueError, match="Unpublished local documentation target"):
        module.stage()
