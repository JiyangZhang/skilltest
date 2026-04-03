import json
import xml.etree.ElementTree as ET
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

from skilltest.models import GradingReport, CoverageReport, DiffReport

# Boilerplate appended by _build_docker_task_prompt() in runner.py.
# Strip it before showing the user's original prompt in the report.
_BOILERPLATE_MARKER = "\n---\n## Required output for SkillTest"


# ── shared HTML helpers ───────────────────────────────────────────────────────

def _escape(s: str) -> str:
    return (str(s).replace("&", "&amp;").replace("<", "&lt;")
                   .replace(">", "&gt;").replace('"', "&quot;"))


def _oracle_badge(oracle: str) -> str:
    color = "#8250df" if oracle == "agent-judge" else "#0550ae"
    return f'<span class="badge" style="background:{color}">{oracle}</span>'


def _read_run_bundle(runs_dir: Path, test_id: int) -> tuple[str | None, str | None]:
    """Return (prompt, agent_output) from the run bundle, or (None, None) if not found."""
    run_dir = runs_dir / f"test-{test_id}"

    prompt = None
    prompt_file = run_dir / "prompt.txt"
    if prompt_file.exists():
        raw = prompt_file.read_text(encoding="utf-8")
        if _BOILERPLATE_MARKER in raw:
            raw = raw[: raw.index(_BOILERPLATE_MARKER)]
        prompt = raw.strip()

    output = None
    stdout_file = run_dir / "output" / "stdout.txt"
    if stdout_file.exists():
        output = stdout_file.read_text(encoding="utf-8").strip()

    return prompt, output


def _render_test_cards(
    by_test: dict[int, list[dict]],
    runs_dir: Path | None = None,
) -> str:
    """Render one card per test_id. Enriches with run bundle data when runs_dir is given."""
    cards = ""
    for test_id in sorted(by_test):
        exps = by_test[test_id]
        tc_pass = sum(1 for e in exps if e.get("passed"))
        tc_total = len(exps)
        header_color = "#166534" if tc_pass == tc_total else "#991b1b"
        icon = "✓" if tc_pass == tc_total else "✗"
        total_ms = sum(e.get("duration_ms", 0) for e in exps)

        prompt, agent_output = (None, None)
        if runs_dir is not None:
            prompt, agent_output = _read_run_bundle(runs_dir, test_id)

        rows = ""
        for e in exps:
            ok = e.get("passed", False)
            status_cls = "pass" if ok else "fail"
            status_icon = "✓" if ok else "✗"
            evidence_row = ""
            if not ok:
                evidence_row = (
                    f'<tr><td colspan="3" class="evidence">'
                    f'{_escape(e.get("evidence", ""))}</td></tr>'
                )
            rows += f"""
            <tr class="{status_cls}">
              <td class="status-cell"><span class="status-icon">{status_icon}</span></td>
              <td>{_escape(e.get("text", ""))}</td>
              <td>{_oracle_badge(e.get("oracle_used", ""))}</td>
            </tr>{evidence_row}"""

        prompt_section = ""
        if prompt:
            prompt_section = (
                f'<div class="section-label">Prompt</div>'
                f'<div class="prompt-box">{_escape(prompt)}</div>'
            )

        output_section = ""
        if agent_output:
            output_section = (
                f'<div class="section-label">Agent output</div>'
                f'<div class="output-box">{_escape(agent_output)}</div>'
            )

        cards += f"""
    <div class="card">
      <div class="card-header" style="border-left:4px solid {header_color}">
        <span class="card-title">{icon} Test {test_id}</span>
        <span class="card-meta">{tc_pass}/{tc_total} passed · {total_ms / 1000:.1f}s</span>
      </div>
      {prompt_section}
      <table class="exp-table">
        <thead><tr><th></th><th>Expectation</th><th>Oracle</th></tr></thead>
        <tbody>{rows}</tbody>
      </table>
      {output_section}
    </div>"""
    return cards


_CSS = """
  :root {
    --bg:           #0d1117;
    --surface:      #161b22;
    --surface2:     #21262d;
    --border:       #30363d;
    --text:         #e6edf3;
    --text-title:   #f0f6fc;
    --text-muted:   #7d8590;
    --text-subtle:  #8b949e;
    --link:         #58a6ff;
    --pass:         #3fb950;
    --fail:         #f85149;
    --row-pass-bg:  #0d2119;
    --row-fail-bg:  #1f0d0d;
    --prompt-bg:    #010409;
    --prompt-text:  #8b949e;
    --output-bg:    #010409;
    --output-text:  #c9d1d9;
    --evidence-bg:  #272115;
    --evidence-text:#e3b341;
    --progress-bg:  #21262d;
    --progress-fill:#238636;
    --row-border:   #21262d;
    --toggle-bg:    #21262d;
    --toggle-border:#30363d;
    --toggle-text:  #8b949e;
  }
  [data-theme="light"] {
    --bg:           #ffffff;
    --surface:      #f6f8fa;
    --surface2:     #eaeef2;
    --border:       #d0d7de;
    --text:         #24292f;
    --text-title:   #1f2328;
    --text-muted:   #6e7781;
    --text-subtle:  #57606a;
    --link:         #0969da;
    --pass:         #1a7f37;
    --fail:         #cf222e;
    --row-pass-bg:  #dafbe1;
    --row-fail-bg:  #ffebe9;
    --prompt-bg:    #f6f8fa;
    --prompt-text:  #57606a;
    --output-bg:    #eaeef2;
    --output-text:  #24292f;
    --evidence-bg:  #fff8c5;
    --evidence-text:#9a6700;
    --progress-bg:  #d0d7de;
    --progress-fill:#1a7f37;
    --row-border:   #eaeef2;
    --toggle-bg:    #f6f8fa;
    --toggle-border:#d0d7de;
    --toggle-text:  #57606a;
  }

  *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
  body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "Noto Sans", Helvetica, Arial, sans-serif;
         background: var(--bg); color: var(--text); min-height: 100vh; transition: background .15s, color .15s; }
  a { color: var(--link); text-decoration: none; }
  a:hover { text-decoration: underline; }

  .topbar { background: var(--surface); border-bottom: 1px solid var(--border); padding: 12px 24px;
            display: flex; align-items: center; gap: 12px; }
  .topbar-title { font-size: 0.95rem; font-weight: 600; color: var(--text-title); }
  .topbar-sep { color: var(--text-muted); }
  .topbar-skill { color: var(--link); font-size: 0.95rem; font-weight: 600; }
  .topbar-time { margin-left: auto; font-size: 0.75rem; color: var(--text-muted); }

  .theme-toggle { background: var(--toggle-bg); color: var(--toggle-text); border: 1px solid var(--toggle-border);
                  border-radius: 6px; padding: 3px 10px; font-size: 0.75rem; font-family: inherit;
                  cursor: pointer; margin-left: 8px; line-height: 20px; }
  .theme-toggle:hover { background: var(--surface2); }

  .hero { background: var(--surface); border-bottom: 1px solid var(--border); padding: 24px; }
  .hero-inner { max-width: 900px; margin: 0 auto; }
  .hero-stats { display: flex; gap: 24px; flex-wrap: wrap; margin-bottom: 16px; }
  .stat { display: flex; flex-direction: column; gap: 1px; }
  .stat-val { font-size: 1.75rem; font-weight: 700; line-height: 1.2; }
  .stat-label { font-size: 0.72rem; color: var(--text-muted); text-transform: uppercase; letter-spacing: .05em; }
  .pass { color: var(--pass); } .fail { color: var(--fail); } .neutral { color: var(--text-subtle); }

  .progress-wrap { background: var(--progress-bg); border-radius: 6px; height: 8px; overflow: hidden; }
  .progress-fill { height: 100%; border-radius: 6px; background: var(--progress-fill); transition: width .5s ease; }

  .meta-row { margin-top: 12px; display: flex; gap: 20px; font-size: 0.78rem; color: var(--text-muted); flex-wrap: wrap; }
  .meta-row span b { color: var(--text-subtle); font-weight: 500; }

  .content { max-width: 900px; margin: 24px auto; padding: 0 24px; }

  .card { background: var(--surface); border: 1px solid var(--border); border-radius: 6px;
          margin-bottom: 16px; overflow: hidden; }
  .card-header { padding: 12px 16px; display: flex; align-items: center; gap: 10px;
                 background: var(--surface2); border-bottom: 1px solid var(--border); }
  .card-title { font-weight: 600; font-size: 0.9rem; color: var(--text-title); }
  .card-meta { margin-left: auto; font-size: 0.75rem; color: var(--text-muted); }

  .section-label { font-size: 0.67rem; font-weight: 600; text-transform: uppercase; letter-spacing: .06em;
                   color: var(--text-muted); padding: 8px 16px 3px; }
  .prompt-box { font-size: 0.8rem; color: var(--prompt-text); background: var(--prompt-bg); padding: 8px 16px 12px;
                border-bottom: 1px solid var(--border); white-space: pre-wrap; font-family: "SFMono-Regular", Consolas, monospace; line-height: 1.5; }
  .output-box { font-size: 0.8rem; color: var(--output-text); background: var(--output-bg); padding: 8px 16px 12px;
                border-top: 1px solid var(--border); white-space: pre-wrap; font-family: "SFMono-Regular", Consolas, monospace; line-height: 1.5; }

  .exp-table { width: 100%; border-collapse: collapse; font-size: 0.83rem; }
  .exp-table thead th { padding: 7px 12px; text-align: left; font-size: 0.7rem; font-weight: 600;
                        text-transform: uppercase; letter-spacing: .05em; color: var(--text-muted);
                        border-bottom: 1px solid var(--border); background: var(--surface2); }
  .exp-table tbody tr.pass { background: var(--row-pass-bg); }
  .exp-table tbody tr.fail { background: var(--row-fail-bg); }
  .exp-table tbody tr td { padding: 9px 12px; border-bottom: 1px solid var(--row-border); vertical-align: top; }
  .exp-table tbody tr:last-child td { border-bottom: none; }
  .status-cell { width: 28px; text-align: center; }
  .status-icon { font-size: 0.9rem; font-weight: 700; }
  tr.pass .status-icon { color: var(--pass); }
  tr.fail .status-icon { color: var(--fail); }
  .evidence { font-size: 0.76rem; color: var(--evidence-text); background: var(--evidence-bg);
              padding: 7px 12px 9px 40px; border-left: 3px solid var(--evidence-text); }

  .badge { display: inline-block; font-size: 0.67rem; font-weight: 500; color: #fff;
           padding: 1px 6px; border-radius: 2em; letter-spacing: .02em; white-space: nowrap; }

  .footer { text-align: center; padding: 32px; font-size: 0.73rem; color: var(--text-muted);
            border-top: 1px solid var(--border); margin-top: 16px; }
"""

_THEME_JS = """
  (function() {
    var saved = localStorage.getItem('skilltest-theme');
    if (saved) document.documentElement.setAttribute('data-theme', saved);
    document.addEventListener('DOMContentLoaded', function() {
      var theme = document.documentElement.getAttribute('data-theme') || 'dark';
      document.getElementById('theme-btn').textContent = theme === 'light' ? '\N{CRESCENT MOON} Dark' : '\N{BLACK SUN WITH RAYS} Light';
    });
  })();
  function toggleTheme() {
    var current = document.documentElement.getAttribute('data-theme') || 'dark';
    var next = current === 'light' ? 'dark' : 'light';
    document.documentElement.setAttribute('data-theme', next);
    localStorage.setItem('skilltest-theme', next);
    document.getElementById('theme-btn').textContent = next === 'light' ? '\N{CRESCENT MOON} Dark' : '\N{BLACK SUN WITH RAYS} Light';
  }
"""


def _render_html(
    skill_name: str,
    pct: int,
    passed: int,
    total: int,
    n_tests: int,
    duration: float,
    docker_image: str,
    generated_at: str,
    test_cards: str,
) -> str:
    pct_color = "pass" if pct == 100 else "fail" if pct < 50 else "neutral"
    failed = total - passed
    failed_color = "fail" if failed > 0 else "pass"
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>SkillTest Report — {_escape(skill_name)}</title>
<style>{_CSS}</style>
<script>{_THEME_JS}</script>
</head>
<body>
<div class="topbar">
  <span class="topbar-title">SkillTest</span>
  <span>›</span>
  <span class="topbar-skill">{_escape(skill_name)}</span>
  <span class="topbar-time">Generated {generated_at}</span>
  <button id="theme-btn" class="theme-toggle" onclick="toggleTheme()">☀ Light</button>
</div>

<div class="hero">
  <div class="hero-inner">
    <div class="hero-stats">
      <div class="stat"><span class="stat-val {pct_color}">{pct}%</span><span class="stat-label">Pass rate</span></div>
      <div class="stat"><span class="stat-val pass">{passed}</span><span class="stat-label">Passed</span></div>
      <div class="stat"><span class="stat-val {failed_color}">{failed}</span><span class="stat-label">Failed</span></div>
      <div class="stat"><span class="stat-val neutral">{total}</span><span class="stat-label">Total checks</span></div>
    </div>
    <div class="progress-wrap"><div class="progress-fill" style="width:{pct}%"></div></div>
    <div class="meta-row">
      <span><b>Duration</b> {duration:.1f}s</span>
      <span><b>Image</b> {_escape(docker_image)}</span>
      <span><b>Tests</b> {n_tests}</span>
    </div>
  </div>
</div>

<div class="content">
  {test_cards}
</div>

<div class="footer">SkillTest · <a href="https://github.com/JiyangZhang/skilltest">github.com/JiyangZhang/skilltest</a></div>
</body>
</html>"""


# ── public writers ────────────────────────────────────────────────────────────

def write_grading(report: GradingReport, output_dir: Path, skill_name: str = "skill") -> tuple[Path, Path]:
    """Write grading.json and grading.xml (JUnit format) to output_dir.

    Returns (json_path, xml_path).
    """
    output_dir.mkdir(parents=True, exist_ok=True)

    # ── JSON ──────────────────────────────────────────────────────────────────
    json_path = output_dir / "grading.json"
    data = {
        "skill_name": skill_name,
        "expectations": [
            {
                "test_id": r.test_id,
                "text": r.text,
                "passed": r.passed,
                "evidence": r.evidence,
                "oracle_used": r.oracle_used.value,
                "duration_ms": r.duration_ms,
            }
            for r in report.expectations
        ],
        "summary": report.summary,
        "execution_metrics": report.execution_metrics,
        "timing": report.timing,
    }
    json_path.write_text(json.dumps(data, indent=2), encoding="utf-8")

    # ── JUnit XML ─────────────────────────────────────────────────────────────
    xml_path = _write_junit_xml(report, output_dir, skill_name)

    return json_path, xml_path


def write_html_report(report: GradingReport, output_dir: Path, skill_name: str = "skill") -> Path:
    """Write report.html during a live run (has access to run bundles in output_dir)."""
    output_dir.mkdir(parents=True, exist_ok=True)

    by_test: dict[int, list[dict]] = defaultdict(list)
    for r in report.expectations:
        by_test[r.test_id].append({
            "text": r.text,
            "passed": r.passed,
            "evidence": r.evidence,
            "oracle_used": r.oracle_used.value,
            "duration_ms": r.duration_ms,
        })

    runs_dir = output_dir / "agent-runs"
    test_cards = _render_test_cards(by_test, runs_dir=runs_dir if runs_dir.is_dir() else None)

    pct = int(report.summary.get("pass_rate", 0) * 100)
    html = _render_html(
        skill_name=skill_name,
        pct=pct,
        passed=report.summary.get("passed", 0),
        total=report.summary.get("total", 0),
        n_tests=len(report.test_results),
        duration=report.execution_metrics.get("total_duration_seconds", 0.0),
        docker_image=report.timing.get("docker_image", "—"),
        generated_at=datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        test_cards=test_cards,
    )
    html_path = output_dir / "report.html"
    html_path.write_text(html, encoding="utf-8")
    return html_path


def write_html_report_from_json(grading_json: Path, output_dir: Path) -> Path:
    """Read a grading.json and write report.html, enriched from adjacent agent-runs/ bundles."""
    data = json.loads(grading_json.read_text(encoding="utf-8"))

    skill_name = data.get("skill_name", "skill")
    summary = data.get("summary", {})
    execution_metrics = data.get("execution_metrics", {})
    timing = data.get("timing", {})

    by_test: dict[int, list[dict]] = defaultdict(list)
    for e in data.get("expectations", []):
        by_test[e["test_id"]].append(e)

    # agent-runs/ sits next to grading.json
    runs_dir = grading_json.parent / "agent-runs"
    test_cards = _render_test_cards(by_test, runs_dir=runs_dir if runs_dir.is_dir() else None)

    pct = int(summary.get("pass_rate", 0) * 100)
    html = _render_html(
        skill_name=skill_name,
        pct=pct,
        passed=summary.get("passed", 0),
        total=summary.get("total", 0),
        n_tests=len(by_test),
        duration=execution_metrics.get("total_duration_seconds", 0.0),
        docker_image=timing.get("docker_image", "—"),
        generated_at=datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        test_cards=test_cards,
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    html_path = output_dir / "report.html"
    html_path.write_text(html, encoding="utf-8")
    return html_path


# ── internal helpers ──────────────────────────────────────────────────────────

def _write_junit_xml(report: GradingReport, output_dir: Path, skill_name: str) -> Path:
    total = report.summary.get("total", 0)
    failed = report.summary.get("failed", 0)
    total_time = report.execution_metrics.get("total_duration_seconds", 0.0)

    testsuites = ET.Element("testsuites", {
        "name": "skilltest",
        "tests": str(total),
        "failures": str(failed),
        "errors": "0",
        "time": f"{total_time:.3f}",
    })
    testsuite = ET.SubElement(testsuites, "testsuite", {
        "name": skill_name,
        "tests": str(total),
        "failures": str(failed),
        "errors": "0",
        "time": f"{total_time:.3f}",
    })

    for r in report.expectations:
        tc = ET.SubElement(testsuite, "testcase", {
            "name": f"[Test {r.test_id}] {r.text}",
            "classname": skill_name,
            "time": f"{r.duration_ms / 1000:.3f}",
        })
        if not r.passed:
            failure = ET.SubElement(tc, "failure", {"message": r.evidence})
            failure.text = r.evidence

    tree = ET.ElementTree(testsuites)
    ET.indent(tree, space="  ")

    xml_path = output_dir / "grading.xml"
    tree.write(str(xml_path), encoding="unicode", xml_declaration=True)
    return xml_path


def write_coverage(report: CoverageReport, output_dir: Path) -> tuple[Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)

    json_path = output_dir / "coverage.json"
    json_path.write_text(json.dumps(report.model_dump(), indent=2), encoding="utf-8")

    md_path = output_dir / "coverage.md"
    lines = [
        f"# Coverage report: {report.skill_name}",
        f"\nOverall coverage: **{int(report.overall_coverage * 100)}%**",
        f"Executor calls made: {report.executor_calls_made}",
        "\n| Section | Score | Verdict |",
        "|---|---|---|",
    ]
    for s in report.sections:
        path_str = " > ".join(s.heading_path)
        lines.append(f"| {path_str} | {s.coverage_score:.2f} | {s.verdict} |")

    if report.dead_sections:
        lines.append("\n## Dead instructions (score 0.0)\n")
        for sid in report.dead_sections:
            sec = next(s for s in report.sections if s.section_id == sid)
            lines.append(f"- `{sid}`: {sec.recommendation}")

    md_path.write_text("\n".join(lines), encoding="utf-8")
    return json_path, md_path


def write_diff(report: DiffReport, output_dir: Path) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / "diff.json"
    path.write_text(json.dumps(report.model_dump(), indent=2), encoding="utf-8")
    return path
