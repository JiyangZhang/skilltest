import pytest
from pathlib import Path
from skilltest.parser import parse_skill
from skilltest.models import SkillParseError, CanonicalSkill

FIXTURES = Path(__file__).parent / "fixtures"


def test_parse_anthropic_skill():
    skill = parse_skill(FIXTURES / "anthropic_skill")
    assert skill.name == "test-skill"
    assert "test skill" in skill.description.lower()
    assert len(skill.body) > 0
    assert len(skill.sections) > 0


def test_parse_openai_skill():
    skill = parse_skill(FIXTURES / "openai_skill")
    assert skill.name == "openai-test-skill"
    assert len(skill.sections) > 0


def test_sections_non_empty():
    skill = parse_skill(FIXTURES / "anthropic_skill")
    assert len(skill.sections) > 0


def test_section_offsets_correct():
    skill = parse_skill(FIXTURES / "anthropic_skill")
    for section in skill.sections:
        extracted = skill.body[section.char_start:section.char_end]
        assert section.raw_text == extracted, (
            f"Section {section.id}: raw_text does not match body slice"
        )


def test_sections_non_overlapping():
    skill = parse_skill(FIXTURES / "anthropic_skill")
    sorted_sections = sorted(skill.sections, key=lambda s: s.char_start)
    for i in range(len(sorted_sections) - 1):
        a = sorted_sections[i]
        b = sorted_sections[i + 1]
        assert a.char_end <= b.char_start, (
            f"Sections overlap: {a.id} ends at {a.char_end}, {b.id} starts at {b.char_start}"
        )


def test_missing_frontmatter_raises():
    import tempfile, os
    with tempfile.TemporaryDirectory() as tmp:
        skill_file = Path(tmp) / "SKILL.md"
        skill_file.write_text("# No frontmatter here\n\nJust a body.", encoding="utf-8")
        with pytest.raises(SkillParseError, match="frontmatter"):
            parse_skill(Path(tmp))


def test_missing_name_raises():
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        skill_file = Path(tmp) / "SKILL.md"
        skill_file.write_text(
            "---\ndescription: A skill without a name\n---\n\nBody here.",
            encoding="utf-8"
        )
        with pytest.raises(SkillParseError, match="name"):
            parse_skill(Path(tmp))


def test_missing_description_raises():
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        skill_file = Path(tmp) / "SKILL.md"
        skill_file.write_text(
            "---\nname: my-skill\n---\n\nBody here.",
            encoding="utf-8"
        )
        with pytest.raises(SkillParseError, match="description"):
            parse_skill(Path(tmp))
