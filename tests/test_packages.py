import importlib

import pytest

PACKAGES = [
    "core",
    "core.sources",
    "core.fetch",
    "core.parse",
    "core.tables",
    "core.publish",
    "core.cli",
    "projects.public_finance",
    "projects.security_means",
    "projects.election_2027",
]


@pytest.mark.parametrize("name", PACKAGES)
def test_package_imports(name: str) -> None:
    assert importlib.import_module(name) is not None
