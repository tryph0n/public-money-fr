import ast
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


def project_names(root: Path) -> set[str]:
    projects_dir = root / "projects"
    return {
        path.name
        for path in projects_dir.iterdir()
        if path.is_dir() and not path.name.startswith(("_", "."))
    }


def imported_modules(path: Path, root: Path) -> list[tuple[int, str]]:
    """Return (line, absolute dotted name) for each name a file imports."""
    package = list(path.relative_to(root).parts[:-1])
    found: list[tuple[int, str]] = []
    for node in ast.walk(ast.parse(path.read_text(), filename=str(path))):
        if isinstance(node, ast.Import):
            found.extend((node.lineno, alias.name) for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                base = package[: len(package) - (node.level - 1)]
                module = ".".join([*base, *([node.module] if node.module else [])])
            else:
                module = node.module or ""
            found.append((node.lineno, module))
            found.extend((node.lineno, f"{module}.{alias.name}") for alias in node.names)
    return found


def referenced_project(dotted: str, projects: set[str]) -> str | None:
    parts = dotted.split(".")
    if len(parts) >= 2 and parts[0] == "projects" and parts[1] in projects:
        return parts[1]
    return None


def find_violations(root: Path) -> list[str]:
    projects = project_names(root)
    violations: list[str] = []
    for source_dir in [root / "core", *(root / "projects" / name for name in sorted(projects))]:
        owner = source_dir.name if source_dir.parent.name == "projects" else "core"
        for path in sorted(source_dir.rglob("*.py")):
            for line, dotted in imported_modules(path, root):
                target = referenced_project(dotted, projects)
                if target is not None and target != owner:
                    where = path.relative_to(root)
                    violations.append(f"{where}:{line} imports projects.{target}")
    return list(dict.fromkeys(violations))


def make_tree(root: Path, files: dict[str, str]) -> None:
    for name in ("core", "projects", "projects/alpha", "projects/beta"):
        (root / name).mkdir(parents=True, exist_ok=True)
        (root / name / "__init__.py").write_text("")
    for name, content in files.items():
        (root / name).write_text(content)


def test_repository_respects_import_boundaries() -> None:
    assert find_violations(ROOT) == []


@pytest.mark.parametrize(
    "statement",
    [
        "import projects.beta",
        "import projects.beta.sub",
        "from projects.beta import thing",
        "from projects import beta",
        "from .. import beta",
        "from ..beta import thing",
    ],
)
def test_project_importing_another_project_is_detected(tmp_path: Path, statement: str) -> None:
    make_tree(tmp_path, {"projects/alpha/mod.py": statement + "\n"})
    assert len(find_violations(tmp_path)) >= 1


@pytest.mark.parametrize(
    "statement",
    [
        "import projects.alpha",
        "from projects.alpha import thing",
        "from projects import alpha",
    ],
)
def test_core_importing_a_project_is_detected(tmp_path: Path, statement: str) -> None:
    make_tree(tmp_path, {"core/mod.py": statement + "\n"})
    assert len(find_violations(tmp_path)) >= 1


def test_allowed_imports_are_not_flagged(tmp_path: Path) -> None:
    source = "import core\nfrom core import x\nimport projects.alpha\nfrom . import y\n"
    make_tree(tmp_path, {"projects/alpha/mod.py": source})
    assert find_violations(tmp_path) == []


def test_new_project_is_covered_without_code_change(tmp_path: Path) -> None:
    make_tree(tmp_path, {})
    (tmp_path / "projects/gamma").mkdir()
    (tmp_path / "projects/gamma/__init__.py").write_text("from projects import alpha\n")
    assert len(find_violations(tmp_path)) == 1
