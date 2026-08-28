"""
Local web server to page through quality-control reports and rate them
"""

import json
import logging
import mimetypes
import os
import sys
import webbrowser
from dataclasses import asdict
from functools import partial
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib.resources import files
from pathlib import Path
from urllib.parse import unquote, urlparse

from mreyextract.viewer.reports import (
    REPORT_PATTERNS,
    RatingStatus,
    find_reports,
    rate_report,
    ratings_path,
)

logger = logging.getLogger(__name__)

PAGE_NAME = "viewer.html"


def viewer_page() -> bytes:
    """
    Read the single-page viewer shipped as package data.

    Returns
    -------
    bytes
        The UTF-8 encoded HTML served at ``/``.
    """
    return (files("mreyextract.viewer") / PAGE_NAME).read_bytes()


class ViewerServer(ThreadingHTTPServer):
    """
    Threading server that keeps ordinary client disconnects out of the console.

    Browsers open several connections per page and drop them whenever a tab is
    closed or a report is navigated away from mid-load. With keep-alive that
    reaches the server as a reset on an idle connection, which the default
    handler would print as a traceback in the middle of a reviewer's session.
    """

    def handle_error(self, request, client_address) -> None:
        """
        Report a failed request, ignoring the client hanging up.

        Parameters
        ----------
        request : socket.socket
            The connection the failing request arrived on.
        client_address : tuple
            Address of the peer.
        """
        if isinstance(sys.exc_info()[1], (ConnectionResetError, BrokenPipeError)):
            logger.debug("Client %s closed the connection", client_address)
            return
        super().handle_error(request, client_address)


class ViewerHandler(BaseHTTPRequestHandler):
    """
    Serve the viewer page, the report files, and the ratings API.

    Reports are re-globbed and ratings re-read on every request rather than held
    in memory, so a browser refresh picks up reports written while the viewer is
    open, and two reviewers on the same dataset see each other's verdicts.

    Parameters
    ----------
    review_dir : Path
        Resolved directory reports are found in and served from.
    patterns : tuple[str, ...]
        Globs used to find reports under ``review_dir``.
    """

    server_version = "mreyextract-viewer"

    # Every response carries a Content-Length, so connections can be kept alive
    # -- worth having when each report is megabytes read over a slow link.
    protocol_version = "HTTP/1.1"

    # Don't let an idle kept-alive connection hold its thread for a whole
    # session; the browser reopens one when the reviewer moves on.
    timeout = 120

    def __init__(self, *args, review_dir: Path, patterns: tuple[str, ...], **kwargs):
        self.review_dir = review_dir
        self.patterns = patterns
        # BaseHTTPRequestHandler answers the request from inside __init__, so
        # everything the routes need has to be set before delegating to it.
        super().__init__(*args, **kwargs)

    def do_GET(self) -> None:  # pylint: disable=invalid-name
        """
        Route a ``GET`` to the page, the report index, or a report file.
        """
        route = unquote(urlparse(self.path).path)

        if route == "/":
            self._send_bytes(viewer_page(), "text/html; charset=utf-8")
        elif route == "/api/reports":
            self._send_json(self._index())
        elif route.startswith("/report/"):
            self._send_report(route.removeprefix("/report/"))
        else:
            self._send_json({"error": f"Unknown route {route}"}, HTTPStatus.NOT_FOUND)

    def do_POST(self) -> None:  # pylint: disable=invalid-name
        """
        Record a verdict submitted from the page.
        """
        route = unquote(urlparse(self.path).path)
        if route != "/api/rating":
            self._send_json({"error": f"Unknown route {route}"}, HTTPStatus.NOT_FOUND)
            return

        length = int(self.headers.get("Content-Length", 0))
        try:
            payload = json.loads(self.rfile.read(length) or b"{}")
        except json.JSONDecodeError:
            self._send_json({"error": "Malformed JSON body"}, HTTPStatus.BAD_REQUEST)
            return

        relative_path = str(payload.get("path", ""))
        if self._resolve(relative_path) is None:
            self._send_json(
                {"error": f"No such report {relative_path}"}, HTTPStatus.NOT_FOUND
            )
            return

        try:
            status = RatingStatus(str(payload.get("status", "")).lower())
        except ValueError:
            self._send_json(
                {"error": f"Unknown status {payload.get('status')!r}"},
                HTTPStatus.BAD_REQUEST,
            )
            return

        rating = rate_report(
            self.review_dir,
            relative_path,
            status,
            note=str(payload.get("note", "")),
        )
        self._send_json({"path": relative_path, "rating": asdict(rating)})

    def log_message(self, format: str, *args) -> None:  # pylint: disable=W0622
        """
        Send the request log to the package logger instead of stderr.

        Parameters
        ----------
        format : str
            Printf-style format string supplied by the base handler.
        *args
            Values interpolated into ``format``.
        """
        logger.debug("%s - %s", self.address_string(), format % args)

    def _index(self) -> dict:
        """
        Build the report index the page renders its list from.

        Returns
        -------
        dict
            The directory under review, the ratings file being written, and
            every report found with the verdict it currently carries.
        """
        reports = find_reports(self.review_dir, self.patterns)
        return {
            "review_dir": str(self.review_dir),
            "ratings_path": str(ratings_path(self.review_dir)),
            "reports": [asdict(report) for report in reports],
        }

    def _resolve(self, relative_path: str) -> Path | None:
        """
        Resolve a requested report path against the review directory.

        Parameters
        ----------
        relative_path : str
            Path taken from the request URL.

        Returns
        -------
        Path | None
            The file to serve, or ``None`` if it does not exist or escapes the
            review directory (``..`` segments, an absolute path, or a symlink
            pointing out of the tree).
        """
        candidate = Path(os.path.normpath(self.review_dir / relative_path)).resolve()
        if not candidate.is_relative_to(self.review_dir) or not candidate.is_file():
            return None
        return candidate

    def _send_report(self, relative_path: str) -> None:
        """
        Serve one report file into the page's viewing frame.

        Parameters
        ----------
        relative_path : str
            Report path relative to the review directory.
        """
        path = self._resolve(relative_path)
        if path is None:
            self._send_json(
                {"error": f"No such report {relative_path}"}, HTTPStatus.NOT_FOUND
            )
            return

        content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        self._send_bytes(path.read_bytes(), content_type)

    def _send_json(self, payload: dict, status: HTTPStatus = HTTPStatus.OK) -> None:
        """
        Send a JSON response.

        Parameters
        ----------
        payload : dict
            Body to serialise.
        status : HTTPStatus, optional
            Response status. Default ``200 OK``.
        """
        body = json.dumps(payload).encode("utf-8")
        self._send_bytes(body, "application/json; charset=utf-8", status)

    def _send_bytes(
        self,
        body: bytes,
        content_type: str,
        status: HTTPStatus = HTTPStatus.OK,
    ) -> None:
        """
        Send a response body.

        Parameters
        ----------
        body : bytes
            Response body.
        content_type : str
            Value for the ``Content-Type`` header.
        status : HTTPStatus, optional
            Response status. Default ``200 OK``.
        """
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        # Re-running extraction with --force rewrites reports in place, so a
        # cached copy would show the reviewer a stale figure.
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)


def serve_reports(
    review_dir: Path | str,
    patterns: tuple[str, ...] | list[str] | None = None,
    host: str = "127.0.0.1",
    port: int = 8000,
    open_browser: bool = True,
) -> None:
    """
    Serve the quality-control viewer until interrupted.

    Parameters
    ----------
    review_dir : Path | str
        Directory holding the reports to review, typically the output of
        :func:`~mreyextract.io.mreyextract_root`.
    patterns : tuple[str, ...] | list[str] | None, optional
        Globs selecting report files. Default
        :data:`~mreyextract.viewer.reports.REPORT_PATTERNS`.
    host : str, optional
        Interface to bind. Default ``"127.0.0.1"``, which keeps the reports off
        the network; only bind a wider interface on a trusted one.
    port : int, optional
        Port to bind. Default ``8000``; ``0`` picks any free port.
    open_browser : bool, optional
        If ``True`` (default) open the viewer in the default browser.

    Returns
    -------
    None

    Raises
    ------
    FileNotFoundError
        If ``review_dir`` does not exist.
    """
    review_dir = Path(review_dir).resolve()
    if patterns is None:
        patterns = REPORT_PATTERNS

    reports = find_reports(review_dir, patterns)
    if len(reports) == 0:
        logger.warning(
            "Could not find any reports in %s matching %s", review_dir, patterns
        )
    else:
        logger.info("Found %d report(s) in %s", len(reports), review_dir)

    handler = partial(ViewerHandler, review_dir=review_dir, patterns=tuple(patterns))

    with ViewerServer((host, port), handler) as server:
        url = f"http://{host}:{server.server_address[1]}"
        logger.info("Serving quality-control viewer on %s (ctrl-c to stop)", url)
        logger.info("Writing ratings to %s", ratings_path(review_dir))

        if open_browser:
            webbrowser.open(url)

        try:
            server.serve_forever()
        except KeyboardInterrupt:
            logger.info("Stopping quality-control viewer")
