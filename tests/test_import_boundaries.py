"""Check that no module reaches across the project boundaries.

A project imports `core` and never another project; `core` imports no project. The
check is a static scan: it reads every `.py` and `.pyi` file under `core/` and under each
folder of `projects/` (only `__pycache__` is skipped, so a folder such as `projects/_shared`
counts as a project). It flags import statements, a bare `import projects` (the module
could then reach any project by attribute), `from projects import *` (the package has no
`__all__`, so a star import binds every project module already loaded), an attribute on
the name `projects` that names another project (`projects.beta.x`), and calls to
`importlib.import_module` or `__import__` whose first argument is a string literal.

Limit: an import built from a string computed at run time (a variable, a concatenation,
an f-string) is out of reach of a static scan, and so is an access to a project through
another name (`p = projects`, then `p.beta`) or through `getattr`.
"""

import ast
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
DYNAMIC_IMPORTERS = {"import_module", "__import__"}


def project_names(root: Path) -> set[str]:
    projects_dir = root / "projects"
    return {
        path.name for path in projects_dir.iterdir() if path.is_dir() and path.name != "__pycache__"
    }


def imported_modules(path: Path, root: Path) -> list[tuple[int, str]]:
    """Return (line, absolute dotted name) for each name a file imports.

    Besides import statements, a call to `importlib.import_module` or `__import__` with
    a string literal as first argument counts as an import of that name, and so does an
    attribute on the name `projects` (`projects.beta` counts as `projects.beta`).
    """
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
            if module != "projects":
                found.append((node.lineno, module))
            found.extend((node.lineno, f"{module}.{alias.name}") for alias in node.names)
        elif isinstance(node, ast.Call):
            literal = dynamic_import_literal(node)
            if literal is not None:
                found.append((node.lineno, literal))
        elif (
            isinstance(node, ast.Attribute)
            and isinstance(node.value, ast.Name)
            and node.value.id == "projects"
        ):
            found.append((node.lineno, f"projects.{node.attr}"))
    return found


def dynamic_import_literal(call: ast.Call) -> str | None:
    """Return the string literal that a dynamic import call names, if any."""
    func = call.func
    name = func.id if isinstance(func, ast.Name) else getattr(func, "attr", None)
    if name not in DYNAMIC_IMPORTERS:
        return None
    first = (
        call.args[0]
        if call.args
        else next((kw.value for kw in call.keywords if kw.arg == "name"), None)
    )
    if isinstance(first, ast.Constant) and isinstance(first.value, str):
        return first.value
    return None


def referenced_project(dotted: str, projects: set[str]) -> str | None:
    parts = dotted.split(".")
    if parts in (["projects"], ["projects", "*"]):
        return ""
    if len(parts) >= 2 and parts[0] == "projects" and parts[1] in projects:
        return parts[1]
    return None


def find_violations(root: Path) -> list[str]:
    projects = project_names(root)
    violations: list[str] = []
    for source_dir in [root / "core", *(root / "projects" / name for name in sorted(projects))]:
        owner = source_dir.name if source_dir.parent.name == "projects" else "core"
        for path in sorted([*source_dir.rglob("*.py"), *source_dir.rglob("*.pyi")]):
            for line, dotted in imported_modules(path, root):
                target = referenced_project(dotted, projects)
                if target is not None and target != owner:
                    where = path.relative_to(root)
                    imported = f"projects.{target}" if target else "projects"
                    violations.append(f"{where}:{line} imports {imported}")
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


@pytest.mark.parametrize("target", ["core/mod.py", "projects/alpha/mod.py"])
@pytest.mark.parametrize("statement", ["import projects", "import projects as p"])
def test_bare_projects_import_is_detected(tmp_path: Path, target: str, statement: str) -> None:
    make_tree(tmp_path, {target: statement + "\n"})
    assert len(find_violations(tmp_path)) == 1


@pytest.mark.parametrize(
    ("target", "statement"),
    [
        ("core/mod.py", "from projects import *"),
        ("projects/alpha/mod.py", "from projects import *"),
        ("projects/alpha/mod.py", "from .. import *"),
    ],
)
def test_star_import_of_projects_is_detected(tmp_path: Path, target: str, statement: str) -> None:
    make_tree(tmp_path, {target: statement + "\n"})
    assert len(find_violations(tmp_path)) == 1


def test_star_import_from_own_project_is_not_flagged(tmp_path: Path) -> None:
    make_tree(
        tmp_path, {"projects/alpha/mod.py": "from projects.alpha import *\nfrom . import *\n"}
    )
    assert find_violations(tmp_path) == []


def test_from_projects_import_of_own_project_is_not_flagged(tmp_path: Path) -> None:
    make_tree(tmp_path, {"projects/alpha/mod.py": "from projects import alpha\n"})
    assert find_violations(tmp_path) == []


@pytest.mark.parametrize(
    "statement",
    [
        'importlib.import_module("projects.beta")',
        'importlib.import_module("projects.beta.sub")',
        'importlib.import_module(name="projects.beta")',
        'import_module("projects.beta")',
        '__import__("projects.beta")',
        'builtins.__import__("projects.beta")',
        'importlib.import_module("projects")',
    ],
)
def test_dynamic_import_of_another_project_is_detected(tmp_path: Path, statement: str) -> None:
    make_tree(tmp_path, {"projects/alpha/mod.py": statement + "\n"})
    assert len(find_violations(tmp_path)) == 1


def test_dynamic_import_in_core_of_any_project_is_detected(tmp_path: Path) -> None:
    make_tree(tmp_path, {"core/mod.py": 'importlib.import_module("projects.alpha")\n'})
    assert len(find_violations(tmp_path)) == 1


def test_allowed_dynamic_imports_are_not_flagged(tmp_path: Path) -> None:
    source = (
        'importlib.import_module("projects.alpha.sub")\n'
        'importlib.import_module("core.x")\n'
        "importlib.import_module(computed)\n"
        'importlib.import_module(".rel", "projects.beta")\n'
    )
    make_tree(tmp_path, {"projects/alpha/mod.py": source})
    assert find_violations(tmp_path) == []


@pytest.mark.parametrize("target", ["core/mod.pyi", "projects/alpha/mod.pyi"])
def test_stub_file_importing_another_project_is_detected(tmp_path: Path, target: str) -> None:
    make_tree(tmp_path, {target: "from projects import beta\n"})
    assert len(find_violations(tmp_path)) == 1


@pytest.mark.parametrize("folder", ["_shared", "_private", "shared"])
def test_any_folder_under_projects_is_a_project(tmp_path: Path, folder: str) -> None:
    make_tree(tmp_path, {})
    (tmp_path / "projects" / folder).mkdir()
    (tmp_path / "projects" / folder / "mod.py").write_text("from projects import alpha\n")
    assert len(find_violations(tmp_path)) == 1


def test_project_importing_an_underscore_project_is_detected(tmp_path: Path) -> None:
    make_tree(tmp_path, {"projects/alpha/mod.py": "import projects._shared\n"})
    (tmp_path / "projects/_shared").mkdir()
    assert len(find_violations(tmp_path)) == 1


def test_pycache_folder_is_not_a_project(tmp_path: Path) -> None:
    make_tree(tmp_path, {})
    (tmp_path / "projects/__pycache__").mkdir()
    assert project_names(tmp_path) == {"alpha", "beta"}


@pytest.mark.parametrize(
    "expression",
    ["projects.beta.x", "projects.beta", "projects.beta.sub.y()", "print(projects.beta)"],
)
def test_attribute_naming_another_project_is_detected(tmp_path: Path, expression: str) -> None:
    source = "import projects.alpha\n" + expression + "\n"
    make_tree(tmp_path, {"projects/alpha/mod.py": source})
    assert len(find_violations(tmp_path)) == 1


def test_attribute_naming_any_project_in_core_is_detected(tmp_path: Path) -> None:
    make_tree(tmp_path, {"core/mod.py": "from projects import x\nprojects.alpha.x\n"})
    assert len(find_violations(tmp_path)) == 1


def test_attribute_naming_own_project_is_not_flagged(tmp_path: Path) -> None:
    source = "import projects.alpha\nprojects.alpha.x\nprojects.alpha.sub.y()\n"
    make_tree(tmp_path, {"projects/alpha/mod.py": source})
    assert find_violations(tmp_path) == []


def test_attribute_that_names_no_project_is_not_flagged(tmp_path: Path) -> None:
    source = "import projects.alpha\nprojects.unknown.x\nother.beta.x\n"
    make_tree(tmp_path, {"projects/alpha/mod.py": source})
    assert find_violations(tmp_path) == []
