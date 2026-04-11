import json
import pytest
from pathlib import Path
import tempfile
from skilltest.diff import diff_reports


def make_grading(tmp_dir: Path, name: str, expectations: list[dict]) -> Path:
    data = {"expectations": expectations, "summary": {}, "execution_metrics": {}, "timing": {}}
    path = tmp_dir / name
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def test_regression_detected():
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        before = make_grading(tmp, "before.json", [
            {"test_name": "t", "text": "output is correct", "passed": True, "evidence": "ok"}
        ])
        after = make_grading(tmp, "after.json", [
            {"test_name": "t", "text": "output is correct", "passed": False, "evidence": "fail"}
        ])
        report = diff_reports(before, after)
        assert len(report.regressions) == 1
        assert report.regressions[0].change_type == "regression"
        assert len(report.fixes) == 0


def test_fix_detected():
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        before = make_grading(tmp, "before.json", [
            {"test_name": "t", "text": "output is correct", "passed": False, "evidence": "fail"}
        ])
        after = make_grading(tmp, "after.json", [
            {"test_name": "t", "text": "output is correct", "passed": True, "evidence": "ok"}
        ])
        report = diff_reports(before, after)
        assert len(report.fixes) == 1
        assert report.fixes[0].change_type == "fix"
        assert len(report.regressions) == 0


def test_stable_passes_counted():
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        before = make_grading(tmp, "before.json", [
            {"test_name": "t", "text": "output is correct", "passed": True, "evidence": "ok"}
        ])
        after = make_grading(tmp, "after.json", [
            {"test_name": "t", "text": "output is correct", "passed": True, "evidence": "ok"}
        ])
        report = diff_reports(before, after)
        assert report.stable_passes == 1
        assert report.stable_fails == 0
        assert len(report.regressions) == 0
        assert len(report.fixes) == 0


def test_stable_fails_counted():
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        before = make_grading(tmp, "before.json", [
            {"test_name": "t", "text": "output is correct", "passed": False, "evidence": "fail"}
        ])
        after = make_grading(tmp, "after.json", [
            {"test_name": "t", "text": "output is correct", "passed": False, "evidence": "fail"}
        ])
        report = diff_reports(before, after)
        assert report.stable_fails == 1
        assert report.stable_passes == 0



def test_net_change_arithmetic():
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        before = make_grading(tmp, "before.json", [
            {"test_name": "a", "text": "check A", "passed": True, "evidence": "ok"},
            {"test_name": "b", "text": "check B", "passed": False, "evidence": "fail"},
            {"test_name": "c", "text": "check C", "passed": False, "evidence": "fail"},
        ])
        after = make_grading(tmp, "after.json", [
            {"test_name": "a", "text": "check A", "passed": False, "evidence": "broke"},
            {"test_name": "b", "text": "check B", "passed": True, "evidence": "fixed"},
            {"test_name": "c", "text": "check C", "passed": True, "evidence": "fixed"},
        ])
        report = diff_reports(before, after)
        assert len(report.regressions) == 1
        assert len(report.fixes) == 2
        assert report.net_change == 1  # 2 fixes - 1 regression
