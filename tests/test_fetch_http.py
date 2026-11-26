import gzip
from collections.abc import Iterator

import pytest

from core.fetch.http import EmptyBodyError, FetchError, HttpClient, RefusalError, unpack
from tests.fake_server import FakeServer, body, reset, running_server


@pytest.fixture
def server() -> Iterator[FakeServer]:
    with running_server() as fake:
        yield fake


def client(attempts: int = 4) -> HttpClient:
    return HttpClient(max_attempts=attempts, backoff=0, sleep=lambda _: None)


def test_reset_then_success(server: FakeServer) -> None:
    server.serve("/f.csv", [reset, reset, body(b"a;b\n1;2\n")])
    assert client().get(server.url + "/f.csv") == b"a;b\n1;2\n"
    assert server.hits["/f.csv"] == 3


def test_server_error_is_retried(server: FakeServer) -> None:
    server.serve("/f.csv", [body(b"oops", "text/plain", 503), body(b"ok")])
    assert client().get(server.url + "/f.csv") == b"ok"
    assert server.hits["/f.csv"] == 2


def test_gives_up_after_max_attempts(server: FakeServer) -> None:
    server.serve("/f.csv", reset)
    with pytest.raises(FetchError, match="gave up after 3 tries"):
        client(3).get(server.url + "/f.csv")
    assert server.hits["/f.csv"] == 3


def test_backoff_doubles_and_is_capped(server: FakeServer) -> None:
    delays: list[float] = []
    server.serve("/f.csv", reset)
    slow = HttpClient(max_attempts=5, backoff=1.0, max_delay=3.0, sleep=delays.append)
    with pytest.raises(FetchError):
        slow.get(server.url + "/f.csv")
    assert delays == [1.0, 2.0, 3.0, 3.0]


@pytest.mark.parametrize("status", [403, 429])
def test_refusal_is_not_retried_and_names_the_host(server: FakeServer, status: int) -> None:
    server.serve("/f.csv", body(b"denied", "text/plain", status))
    with pytest.raises(RefusalError, match="127.0.0.1") as error:
        client().get(server.url + "/f.csv")
    assert str(status) in str(error.value)
    assert server.hits["/f.csv"] == 1


def test_robot_page_is_a_refusal(server: FakeServer) -> None:
    server.serve("/f.csv", body(b"<html><body>Are you a robot?</body></html>", "text/html"))
    with pytest.raises(RefusalError, match="127.0.0.1"):
        client().get(server.url + "/f.csv")
    assert server.hits["/f.csv"] == 1


def test_robot_page_under_a_data_content_type_is_a_refusal(server: FakeServer) -> None:
    server.serve("/f.csv", body(b"  <!DOCTYPE html><title>wall</title>", "text/csv"))
    with pytest.raises(RefusalError):
        client().get(server.url + "/f.csv")


def test_html_can_be_allowed(server: FakeServer) -> None:
    server.serve("/page", body(b"<html></html>", "text/html"))
    assert client().get(server.url + "/page", allow_html=True) == b"<html></html>"


def test_other_client_error_is_not_retried(server: FakeServer) -> None:
    with pytest.raises(FetchError, match="HTTP 404"):
        client().get(server.url + "/missing")
    assert server.hits["/missing"] == 1


def test_gzip_body_is_unpacked_by_its_first_bytes(server: FakeServer) -> None:
    server.serve("/f.csv", body(b"a;b\n1;2\n", gzipped=True))
    assert client().get(server.url + "/f.csv") == b"a;b\n1;2\n"


def test_zero_byte_body_is_rejected(server: FakeServer) -> None:
    server.serve("/f.csv", body(b""))
    with pytest.raises(EmptyBodyError, match="127.0.0.1"):
        client().get(server.url + "/f.csv")


def test_gzip_of_nothing_is_rejected() -> None:
    with pytest.raises(EmptyBodyError):
        unpack(gzip.compress(b""), "http://example.org/f")


def test_broken_gzip_is_rejected() -> None:
    with pytest.raises(FetchError, match="invalid gzip"):
        unpack(b"\x1f\x8bnot a stream", "http://example.org/f")
