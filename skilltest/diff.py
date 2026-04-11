import json
from pathlib import Path
from skilltest.models import DiffReport, ExpectationDiff


def load_grading(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def diff_reports(before_path: Path, after_path: Path) -> DiffReport:
    before = load_grading(before_path)
    after = load_grading(after_path)

    def index(report: dict) -> dict[tuple[str, str], bool]:
        return {
            (e["test_name"], e["text"]): e["passed"]
            for e in report.get("expectations", [])
        }

    before_idx = index(before)
    after_idx = index(after)
    all_keys = set(before_idx) | set(after_idx)

    regressions, fixes = [], []
    stable_passes = stable_fails = 0

    for key in sorted(all_keys):
        test_name, text = key
        b = before_idx.get(key)
        a = after_idx.get(key)

        if b is True and a is False:
            regressions.append(ExpectationDiff(
                test_name=test_name, text=text, before=True, after=False, change_type="regression"))
        elif b is False and a is True:
            fixes.append(ExpectationDiff(
                test_name=test_name, text=text, before=False, after=True, change_type="fix"))
        elif b is True and a is True:
            stable_passes += 1
        else:
            stable_fails += 1

    return DiffReport(
        before_path=str(before_path),
        after_path=str(after_path),
        regressions=regressions,
        fixes=fixes,
        stable_passes=stable_passes,
        stable_fails=stable_fails,
        net_change=len(fixes) - len(regressions),
    )
