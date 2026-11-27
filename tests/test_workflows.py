import os
import subprocess
from pathlib import Path
from typing import Any

import yaml

WORKFLOWS = Path(__file__).parent.parent / ".github" / "workflows"


def load(name: str) -> dict[str, Any]:
    return yaml.safe_load((WORKFLOWS / name).read_text(encoding="utf-8"))


def test_both_workflows_that_write_to_hugging_face_share_one_group() -> None:
    groups = [load(n)["concurrency"] for n in ("data-refresh.yml", "hf-publish-check.yml")]
    assert groups[0] == groups[1]
    assert groups[0]["cancel-in-progress"] is False


def test_refresh_installs_runtime_dependencies_only_and_writes_no_contents() -> None:
    workflow = load("data-refresh.yml")
    runs = [step["run"] for step in workflow["jobs"]["refresh"]["steps"] if "run" in step]
    syncs = [run for run in runs if "uv sync" in run]
    assert syncs
    assert all("--no-dev" in run and "--locked" in run for run in syncs)
    assert workflow["permissions"] == {"contents": "read", "issues": "write"}


def test_refresh_steps_use_bash_so_that_a_failure_before_tee_stops_the_run() -> None:
    assert load("data-refresh.yml")["defaults"]["run"]["shell"] == "bash"


SCRIPT = WORKFLOWS.parent / "scripts" / "report-refresh-failure.sh"
FAKE_GH = """#!/usr/bin/env bash
echo "$*" >> "$CALLS"
if [ "$2" = list ]; then
  printf '%s' "${OPEN_ISSUE:-}"
  exit 0
fi
while [ $# -gt 0 ]; do
  if [ "$1" = --body-file ]; then cp "$2" "$POSTED"; fi
  shift
done
"""


def run_script(
    tmp_path: Path,
    log: bytes | None,
    step: str = "fetch",
    token: str = "",
    open_issue: str = "",
    use_log_dir: bool = True,
    locale: str | None = None,
) -> tuple[str, str]:
    """Run the report script with a fake `gh`; return the posted text and the `gh` calls."""
    fake = tmp_path / "bin" / "gh"
    fake.parent.mkdir()
    fake.write_text(FAKE_GH, encoding="utf-8")
    fake.chmod(0o755)
    logs = tmp_path / "logs"
    logs.mkdir()
    if log is not None:
        (logs / f"{step}.log").write_bytes(log + b"\n")
    posted = tmp_path / "posted.txt"
    calls = tmp_path / "calls.txt"
    env = {
        "PATH": f"{fake.parent}:{os.environ['PATH']}",
        "FAILED_STEP": step,
        "RUN_URL": "https://example.test/run/1",
        "POSTED": str(posted),
        "CALLS": str(calls),
        "HF_TOKEN": token,
        "OPEN_ISSUE": open_issue,
    }
    if locale is not None:
        env["LANG"] = locale
    if use_log_dir:
        env["LOG_DIR"] = str(logs)
    subprocess.run(["bash", str(SCRIPT)], env=env, check=True, capture_output=True)
    return posted.read_text(encoding="utf-8"), calls.read_text(encoding="utf-8")


def post(tmp_path: Path, error_line: str, step: str = "fetch", token: str = "") -> str:
    return run_script(tmp_path, error_line.encode(), step, token)[0]


def test_error_line_is_fenced_longer_than_its_backticks(tmp_path: Path) -> None:
    line = "ERROR @maintainer see ````` [x](https://a.test) https://b.test/x"
    lines = post(tmp_path, line).splitlines()
    fence = "`" * 6
    assert lines[0] == fence
    closing = lines.index(fence, 1)
    assert any(item.endswith(line) for item in lines[1:closing])


def test_token_value_is_not_posted(tmp_path: Path) -> None:
    text = post(tmp_path, "ERROR upload refused for secret-value-123", token="secret-value-123")
    assert "secret-value-123" not in text
    assert "ERROR upload refused for ***" in text


def test_issue_opens_when_the_log_folder_is_not_set(tmp_path: Path) -> None:
    text, calls = run_script(tmp_path, None, step="setup", use_log_dir=False)
    assert "issue create" in calls
    assert "Step: setup" in text


def test_a_very_long_error_line_is_cut_and_posted_from_a_file(tmp_path: Path) -> None:
    text, calls = run_script(tmp_path, b"ERROR start " + b"x" * 300_000)
    assert "issue create" in calls
    assert "--body-file" in calls
    assert len(text) < 65_536
    assert "ERROR start xxx" in text
    assert "cut to 2000 characters" in text


def test_a_cut_does_not_leave_part_of_a_token(tmp_path: Path) -> None:
    token = "secret-value-123"
    line = "ERROR " + "x" * 1984 + token + "y" * 100
    text, _ = run_script(tmp_path, line.encode(), token=token)
    pieces = [token[i : i + 6] for i in range(len(token) - 5)]
    assert not any(piece in text for piece in pieces)
    assert "***" in text
    assert "cut to 2000 characters" in text


def test_a_null_byte_in_the_log_keeps_the_error_line(tmp_path: Path) -> None:
    text, _ = run_script(tmp_path, b"ERROR bad\x00byte")
    assert "Error: ERROR bad" in text


def test_only_issues_of_the_workflow_are_found_and_the_open_one_gets_the_comment(
    tmp_path: Path,
) -> None:
    text, calls = run_script(tmp_path, b"ERROR again", open_issue="42")
    listing = next(line for line in calls.splitlines() if line.startswith("issue list"))
    assert "--author app/github-actions" in listing
    assert "issue comment 42" in calls
    assert "issue create" not in calls
    assert "ERROR again" in text


def test_the_cut_counts_characters_under_the_c_locale(tmp_path: Path) -> None:
    body = run_script(tmp_path, ("ERROR " + "\u20ac" * 3000).encode(), locale="C")[0]
    assert "cut to 2000 characters" in body
