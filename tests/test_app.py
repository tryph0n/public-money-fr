import re
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

APP_DIR = Path(__file__).resolve().parent.parent / "app"
PAGES = sorted(APP_DIR.glob("pages/*.py"))
SCRIPTS = [APP_DIR / "Home.py", *PAGES]
IDS = [path.name for path in SCRIPTS]
LFI = re.compile(r"\bLFI\b", re.IGNORECASE)
NAMES_FORBIDDEN_ON_ELECTION_PAGE = [
    "Macron",
    "Le Pen",
    "Mélenchon",
    "Retailleau",
    "Bardella",
    "Renaissance",
    "Rassemblement national",
    "Insoumise",
    "Républicains",
    "Parti socialiste",
]


def page_text(app: AppTest) -> str:
    elements = [*app.title, *app.header, *app.markdown, *app.caption, *app.info]
    return "\n".join(element.value for element in elements)


def run(path: Path) -> AppTest:
    app = AppTest.from_file(str(path), default_timeout=30).run()
    assert not app.exception
    return app


def test_expected_pages_exist() -> None:
    assert [path.name for path in PAGES] == [
        "1_Finances_publiques.py",
        "2_Sécurité.py",
        "3_Élection_2027.py",
        "4_À_propos_des_données.py",
    ]


@pytest.mark.parametrize("path", SCRIPTS, ids=IDS)
def test_page_runs_and_has_a_title(path: Path) -> None:
    assert run(path).title


@pytest.mark.parametrize("path", SCRIPTS, ids=IDS)
def test_page_has_no_lfi(path: Path) -> None:
    assert not LFI.search(page_text(run(path)))
    assert not LFI.search(path.read_text())


def test_home_has_three_sections_and_wake_up_notice() -> None:
    app = run(APP_DIR / "Home.py")
    assert [header.value for header in app.header] == [
        "Finances publiques",
        "Sécurité",
        "Élection 2027",
    ]
    assert any("minute" in info.value for info in app.info)


def test_election_page_names_no_candidate() -> None:
    text = page_text(run(APP_DIR / "pages" / "3_Élection_2027.py"))
    assert not [name for name in NAMES_FORBIDDEN_ON_ELECTION_PAGE if name in text]
