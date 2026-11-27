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
