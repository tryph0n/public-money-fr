import importlib
import importlib.util

import pytest

PACKAGES = [
    "core",
    "core.sources",
    "core.fetch",
    "core.parse",
    "core.tables",
    "core.publish",
    "projects.public_finance",
    "projects.security_means",
    "projects.election_2027",
]

MODULES = ["core.cli"]


@pytest.mark.parametrize("name", PACKAGES)
def test_package_has_init_file(name: str) -> None:
    spec = importlib.util.find_spec(name)
    assert spec is not None
    assert spec.origin is not None, f"{name} is a namespace package: __init__.py is missing"
    assert spec.origin.endswith("__init__.py")


@pytest.mark.parametrize("name", MODULES)
def test_module_imports(name: str) -> None:
    assert importlib.import_module(name) is not None
