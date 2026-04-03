import re
import yaml
from pathlib import Path
from skilltest.models import CanonicalSkill, SkillFormat, SkillSection, SkillParseError

FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)


def parse_skill(skill_path: Path) -> CanonicalSkill:
    skill_dir = skill_path if skill_path.is_dir() else skill_path.parent
    skill_file = skill_dir / "SKILL.md"
    if not skill_file.exists():
        raise SkillParseError(f"No SKILL.md found at {skill_file}")

    raw = skill_file.read_text(encoding="utf-8")
    match = FRONTMATTER_RE.match(raw)
    if not match:
        raise SkillParseError("SKILL.md must begin with YAML frontmatter (--- ... ---)")

    fm = yaml.safe_load(match.group(1))
    name = fm.get("name", "").strip()
    description = fm.get("description", "").strip()
    if not name:
        raise SkillParseError("SKILL.md frontmatter must include 'name'")
    if not description:
        raise SkillParseError("SKILL.md frontmatter must include 'description'")

    body = raw[match.end():]
    sections = _parse_sections(body)

    return CanonicalSkill(
        name=name,
        description=description,
        body=body,
        sections=sections,
        source_format=SkillFormat.ANTHROPIC,
        source_path=str(skill_file),
    )


def _parse_sections(body: str) -> list[SkillSection]:
    sections = []
    h2_blocks = re.split(r"(?=^## )", body, flags=re.MULTILINE)
    offset = 0
    for block in h2_blocks:
        if not block.strip():
            offset += len(block)
            continue
        heading = re.match(r"^## (.+)$", block, re.MULTILINE)
        h2_name = heading.group(1).strip() if heading else "preamble"
        h3_blocks = re.split(r"(?=^### )", block, flags=re.MULTILINE)
        h3_offset = offset
        for h3_block in h3_blocks:
            h3_heading = re.match(r"^### (.+)$", h3_block, re.MULTILINE)
            h3_name = h3_heading.group(1).strip() if h3_heading else None
            heading_path = [h2_name] + ([h3_name] if h3_name else [])
            _extract_list_items(h3_block, heading_path, h3_offset, sections)
            h3_offset += len(h3_block)
        offset += len(block)
    return sections


def _slugify(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")


def _extract_list_items(block: str, heading_path: list[str],
                        base_offset: int, sections: list[SkillSection]):
    item_re = re.compile(r"^(?:\d+\.|[-*•])\s+(.+?)(?=\n(?:\d+\.|[-*•])\s|\Z)",
                         re.MULTILINE | re.DOTALL)
    parent_id = ".".join(_slugify(h) for h in heading_path)
    for i, m in enumerate(item_re.finditer(block)):
        item_id = f"{parent_id}.item_{i+1}"
        sections.append(SkillSection(
            id=item_id,
            heading_path=heading_path + [f"item {i+1}"],
            raw_text=m.group(0),
            char_start=base_offset + m.start(),
            char_end=base_offset + m.end(),
        ))
    if not item_re.search(block):
        section_id = ".".join(_slugify(h) for h in heading_path) or "body"
        sections.append(SkillSection(
            id=section_id,
            heading_path=heading_path,
            raw_text=block,
            char_start=base_offset,
            char_end=base_offset + len(block),
        ))
