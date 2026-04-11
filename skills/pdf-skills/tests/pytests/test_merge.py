"""
Test 2: PDF merge.

The agent merges chapter1.pdf (1 page) and chapter2.pdf (2 pages)
into output/artifacts/merged.pdf. We check that:
  - merged.pdf exists in artifacts
  - merged.pdf is a valid PDF with exactly 3 pages
"""
import os
from pathlib import Path


def test_merged_pdf_exists():
    artifacts = Path(os.environ["SKILLTEST_ARTIFACTS_DIR"])
    merged = artifacts / "merged.pdf"
    assert merged.exists(), (
        f"Expected merged.pdf in {artifacts}, but it was not created.\n"
        f"Files found: {list(artifacts.iterdir()) if artifacts.exists() else 'directory missing'}"
    )


def test_merged_pdf_has_three_pages():
    artifacts = Path(os.environ["SKILLTEST_ARTIFACTS_DIR"])
    merged = artifacts / "merged.pdf"
    if not merged.exists():
        import pytest
        pytest.skip("merged.pdf not found — skipping page count check")

    from pypdf import PdfReader
    reader = PdfReader(str(merged))
    assert len(reader.pages) == 3, (
        f"Expected merged PDF to have 3 pages (1 from chapter1 + 2 from chapter2), "
        f"got {len(reader.pages)}"
    )
