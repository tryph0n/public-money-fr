import io

import pyarrow.parquet as pq
import pytest

from core.publish import hf_check


class FakeApi:
    def __init__(self, *, upload_survives_delete: bool = False) -> None:
        self.files: dict[str, bytes] = {}
        self.calls: list[str] = []
        self.keep = upload_survives_delete

    def create_repo(self, repo_id: str, *, repo_type: str, exist_ok: bool) -> object:
        assert repo_type == "dataset"
        assert exist_ok is True
        self.calls.append("create")
        return None

    def file_exists(self, repo_id: str, filename: str, *, repo_type: str) -> bool:
        return filename in self.files

    def upload_file(
        self,
        *,
        path_or_fileobj: bytes,
        path_in_repo: str,
        repo_id: str,
        repo_type: str,
        commit_message: str,
    ) -> object:
        self.calls.append(f"upload:{path_in_repo}")
        self.files[path_in_repo] = path_or_fileobj
        return None

    def delete_file(
        self, path_in_repo: str, repo_id: str, *, repo_type: str, commit_message: str
    ) -> object:
        self.calls.append(f"delete:{path_in_repo}")
        if not self.keep:
            del self.files[path_in_repo]
        return None


def test_repo_ids() -> None:
    assert hf_check.repo_ids() == [
        "sam-bot/public-money-core",
        "sam-bot/public-money-finance",
        "sam-bot/public-money-security",
        "sam-bot/public-money-election",
    ]


def test_card_has_metadata_and_repository_link() -> None:
    card = hf_check.build_card("sam-bot/public-money-core")
    assert card.startswith("---\nlicense: etalab-2.0\nlanguage:\n- fr\n")
    assert card.count("---\n") == 2
    assert "# public-money-core" in card
    assert hf_check.REPOSITORY_URL in card


def test_test_file_is_valid_parquet() -> None:
    table = pq.read_table(io.BytesIO(hf_check.build_test_parquet()))
    assert table.num_rows == 2


def test_check_repo_leaves_only_the_card() -> None:
    api = FakeApi()
    hf_check.check_repo(api, "sam-bot/public-money-core")
    assert list(api.files) == ["README.md"]
    assert api.calls == [
        "create",
        "upload:README.md",
        f"upload:{hf_check.TEST_FILE_PATH}",
        f"delete:{hf_check.TEST_FILE_PATH}",
    ]


def test_check_repo_twice_keeps_the_card_unchanged() -> None:
    api = FakeApi()
    api.files["README.md"] = b"custom card"
    hf_check.check_repo(api, "sam-bot/public-money-core")
    hf_check.check_repo(api, "sam-bot/public-money-core")
    assert api.files == {"README.md": b"custom card"}


def test_check_repo_fails_when_removal_has_no_effect() -> None:
    api = FakeApi(upload_survives_delete=True)
    with pytest.raises(RuntimeError, match="still present"):
        hf_check.check_repo(api, "sam-bot/public-money-core")


def test_main_fails_without_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("HF_TOKEN", raising=False)
    assert hf_check.main() == 1
