import gzip
import threading
from collections import Counter
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

Behaviour = Callable[[BaseHTTPRequestHandler], None]


def body(
    data: bytes, content_type: str = "text/csv", status: int = 200, gzipped: bool = False
) -> Behaviour:
    """Answer with a fixed body; `gzipped` sends a gzip stream under a plain name."""

    def respond(handler: BaseHTTPRequestHandler) -> None:
        payload = gzip.compress(data) if gzipped else data
        handler.send_response(status)
        handler.send_header("Content-Type", content_type)
        handler.send_header("Content-Length", str(len(payload)))
        handler.end_headers()
        handler.wfile.write(payload)

    return respond


def reset(handler: BaseHTTPRequestHandler) -> None:
    """Close the connection without an answer."""
    handler.close_connection = True
    handler.connection.close()


class FakeServer:
    """Routes a path to a behaviour, or to a list of behaviours used one per request."""

    def __init__(self) -> None:
        self.routes: dict[str, Behaviour | list[Behaviour]] = {}
        self.hits: Counter[str] = Counter()
        self.url = ""

    def serve(self, path: str, behaviour: Behaviour | list[Behaviour]) -> None:
        self.routes[path] = behaviour

    def handle(self, handler: BaseHTTPRequestHandler) -> None:
        path = handler.path
        index = self.hits[path]
        self.hits[path] += 1
        route = self.routes.get(path)
        if route is None:
            body(b"not found", "text/plain", 404)(handler)
        elif isinstance(route, list):
            route[min(index, len(route) - 1)](handler)
        else:
            route(handler)


@contextmanager
def running_server() -> Iterator[FakeServer]:
    fake = FakeServer()

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            fake.handle(self)

        def log_message(self, format: str, *args: object) -> None:
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    fake.url = f"http://127.0.0.1:{server.server_address[1]}"
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield fake
    finally:
        server.shutdown()
        server.server_close()
        thread.join()
