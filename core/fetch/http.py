"""HTTP client for the source portals.

A reset connection or a server error is retried with a growing delay. A refusal is never
retried and never worked around: HTTP 401, 403 or 429, or a web page where a data file was
asked for (a robot wall), stops the run with an error that names the host.
"""

import gzip
import http.client
import logging
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from urllib.parse import urlsplit

from core.parse.decoding import GZIP_MAGIC

logger = logging.getLogger(__name__)

USER_AGENT = "public-money-fr (+https://github.com/tryph0n/public-money-fr)"

#: Status codes of a refusal. A retry cannot change the answer and could worsen it.
REFUSAL_STATUSES = (401, 403, 429)

_HTML_STARTS = (b"<!doctype html", b"<html")


class FetchError(Exception):
    """A file could not be fetched or registered."""


class RefusalError(FetchError):
    """A host refused the request. The message names the host."""


class EmptyBodyError(FetchError):
    """The server sent a body of zero bytes."""


class OfflineError(FetchError):
    """The offline mode needs a file that is not in the cache."""


def host_of(url: str) -> str:
    """Return the host name of a URL, for error messages.

    Args:
        url: An absolute URL.

    Returns:
        The host name without the port, or the URL itself if it has no host.
    """
    return urlsplit(url).hostname or url


def unpack(body: bytes, url: str) -> bytes:
    """Decompress a body that starts with the gzip signature and reject an empty result.

    The signature is tested on the first bytes, not on a header or a file name: a server may
    send a gzip stream under a plain name.

    Args:
        body: The bytes received, or the bytes of a file.
        url: Where they come from, for the error message.

    Returns:
        The bytes, decompressed if they were a gzip stream.

    Raises:
        EmptyBodyError: If the result has zero bytes.
        FetchError: If the bytes start like gzip but are not a valid stream.
    """
    if body.startswith(GZIP_MAGIC):
        try:
            body = gzip.decompress(body)
        except (OSError, EOFError) as error:
            raise FetchError(f"{host_of(url)}: invalid gzip body from {url}: {error}") from error
    if not body:
        raise EmptyBodyError(f"{host_of(url)}: zero-byte body from {url}")
    return body


def _looks_like_web_page(body: bytes, content_type: str) -> bool:
    if content_type.lower().startswith("text/html"):
        return True
    return body.lstrip()[:15].lower().startswith(_HTML_STARTS)


class HttpClient:
    """Fetch URLs with retries on resets and server errors."""

    def __init__(
        self,
        *,
        max_attempts: int = 8,
        backoff: float = 1.0,
        max_delay: float = 30.0,
        timeout: float = 60.0,
        sleep: Callable[[float], None] | None = None,
    ) -> None:
        """Set the retry policy.

        Args:
            max_attempts: Number of tries for one URL, the first one included.
            backoff: Delay in seconds before the first retry; it doubles at each retry.
            max_delay: Longest delay in seconds between two tries.
            timeout: Seconds to wait for the server on one try.
            sleep: Function that waits; `time.sleep` if omitted. Tests replace it.
        """
        self.max_attempts = max_attempts
        self.backoff = backoff
        self.max_delay = max_delay
        self.timeout = timeout
        self._sleep = sleep if sleep is not None else time.sleep

    def get(self, url: str, *, allow_html: bool = False) -> bytes:
        """Return the body of a URL, decompressed if it is a gzip stream.

        Args:
            url: The absolute URL.
            allow_html: Accept a web page as the answer. Leave it false for data files and
                for JSON: a web page there is a robot wall or an error page.

        Returns:
            The bytes of the body. Never empty.

        Raises:
            RefusalError: On HTTP 401, 403 or 429, or on a web page that was not allowed. It
                is raised at the first try and names the host.
            EmptyBodyError: If the body has zero bytes.
            FetchError: On any other HTTP error, or when every try failed.
        """
        host = host_of(url)
        last_error = ""
        for attempt in range(1, self.max_attempts + 1):
            try:
                body, content_type = self._once(url)
            except urllib.error.HTTPError as error:
                if error.code in REFUSAL_STATUSES:
                    raise RefusalError(
                        f"{host} refused the request (HTTP {error.code}): {url}"
                    ) from error
                if error.code < 500:
                    raise FetchError(f"{host}: HTTP {error.code} for {url}") from error
                last_error = f"HTTP {error.code}"
            except (urllib.error.URLError, http.client.HTTPException, OSError) as error:
                last_error = f"{type(error).__name__}: {error}"
            else:
                if not allow_html and _looks_like_web_page(body, content_type):
                    raise RefusalError(
                        f"{host} answered with a web page instead of data (robot wall?): {url}"
                    )
                return unpack(body, url)
            if attempt < self.max_attempts:
                delay = min(self.backoff * 2 ** (attempt - 1), self.max_delay)
                logger.warning(
                    "%s: %s (try %d of %d), retrying in %.1f s",
                    host,
                    last_error,
                    attempt,
                    self.max_attempts,
                    delay,
                )
                self._sleep(delay)
        raise FetchError(f"{host}: gave up after {self.max_attempts} tries ({last_error}): {url}")

    def _once(self, url: str) -> tuple[bytes, str]:
        request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(request, timeout=self.timeout) as response:
            return response.read(), response.headers.get("Content-Type", "")
