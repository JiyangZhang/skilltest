import tempfile
from pathlib import Path

from skilltest.run_bundle import (
    prepare_run_directory,
    read_run_bundle,
    summarize_artifacts_for_judge,
)


def test_prepare_and_read_roundtrip():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp) / "run1"
        inp = Path(tmp) / "in"
        inp.mkdir()
        (inp / "sample.txt").write_text("hello", encoding="utf-8")
        prepare_run_directory(root, prompt_text="do the task", input_src=inp)
        assert (root / "prompt.txt").read_text() == "do the task"
        assert (root / "input" / "sample.txt").read_text() == "hello"
        (root / "output" / "stdout.txt").write_text('{"ok": true}', encoding="utf-8")
        bundle = read_run_bundle(root)
        assert bundle.stdout_text == '{"ok": true}'
        assert bundle.artifacts_dir.is_dir()


def test_summarize_artifacts_empty():
    with tempfile.TemporaryDirectory() as tmp:
        ad = Path(tmp) / "a"
        ad.mkdir()
        s = summarize_artifacts_for_judge(ad)
        assert "empty" in s.lower()


def test_summarize_artifacts_with_files():
    with tempfile.TemporaryDirectory() as tmp:
        ad = Path(tmp)
        (ad / "out.json").write_text('{"x": 1}', encoding="utf-8")
        s = summarize_artifacts_for_judge(ad, max_files=5)
        assert "out.json" in s
        assert "x" in s
