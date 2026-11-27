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
if [ "$2" = create ]; then
  while [ $# -gt 0 ]; do
    if [ "$1" = --body ]; then printf '%s' "$2" > "$POSTED"; fi
    shift
  done
fi
"""


def post(tmp_path: Path, error_line: str, step: str = "fetch", token: str = "") -> str:
    """Run the report script with a fake `gh` and return the text it would post."""
    fake = tmp_path / "bin" / "gh"
    fake.parent.mkdir()
    fake.write_text(FAKE_GH, encoding="utf-8")
    fake.chmod(0o755)
    logs = tmp_path / "logs"
    logs.mkdir()
    (logs / f"{step}.log").write_text(error_line + "\n", encoding="utf-8")
    posted = tmp_path / "posted.txt"
    env = {
        "PATH": f"{fake.parent}:{os.environ['PATH']}",
        "FAILED_STEP": step,
        "LOG_DIR": str(logs),
        "RUN_URL": "https://example.test/run/1",
        "POSTED": str(posted),
        "HF_TOKEN": token,
    }
    subprocess.run(["bash", str(SCRIPT)], env=env, check=True, capture_output=True)
    return posted.read_text(encoding="utf-8")


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
