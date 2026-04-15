from pathlib import Path
import re


def _extract(name: str, text: str) -> str | None:
    # Supports:
    #   key = "value"
    #   key = 'value'
    #   key: str = "value"
    #   key: Union[str, None] = 'value'
    m = re.search(
        rf"^{name}(?:\s*:\s*[^=]+)?\s*=\s*['\"]([^'\"]+)['\"]",
        text,
        re.MULTILINE,
    )
    return m.group(1) if m else None


def test_alembic_down_revision_references_existing_revision_ids():
    versions_dir = Path(__file__).resolve().parents[1] / "alembic" / "versions"
    py_files = sorted(versions_dir.glob("*.py"))

    revisions: set[str] = set()
    down_refs: list[tuple[str, str, str]] = []

    for path in py_files:
        text = path.read_text(encoding="utf-8")
        revision = _extract("revision", text)
        if not revision:
            continue
        revisions.add(revision)

        down = _extract("down_revision", text)
        if down:
            down_refs.append((path.name, revision, down))

    invalid = [(f, r, d) for (f, r, d) in down_refs if d not in revisions]

    assert not invalid, (
        "Alembic chain has unknown down_revision reference(s): "
        + ", ".join([f"{f}:{r}->{d}" for (f, r, d) in invalid])
    )
