"""Assert skills/vision/SKILL.md documents open-question marker formats."""
import pathlib


_SKILL_PATH = pathlib.Path(__file__).parent.parent / "skills" / "vision" / "SKILL.md"


def _skill_text() -> str:
    return _SKILL_PATH.read_text(encoding="utf-8")


def test_skill_documents_yaml_frontmatter_format():
    """SKILL.md must contain the YAML frontmatter open_questions: example."""
    assert "open_questions:" in _skill_text()


def test_skill_documents_inline_open_marker():
    """SKILL.md must document the inline `open:` marker."""
    text = _skill_text()
    assert "open:" in text


def test_skill_documents_inline_unresolved_marker():
    """SKILL.md must document the inline `unresolved:` marker."""
    text = _skill_text()
    assert "unresolved:" in text
