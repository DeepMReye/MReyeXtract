"""Tests for :mod:`mreyextract.viewer.server`."""

import json
import threading
from functools import partial
from http.client import HTTPConnection
from pathlib import Path

import pytest

from mreyextract.viewer import server
from mreyextract.viewer.reports import (
    REPORT_PATTERNS,
    Rating,
    RatingStatus,
    ratings_path,
    read_ratings,
)
from mreyextract.viewer.server import ViewerHandler, ViewerServer, serve_reports

REPORT = "sub-01/func/sub-01_task-rest_run-1_desc-eye_report.html"


@pytest.fixture
def client(review_dir: Path):
    """A connection to a viewer served on a free port over ``review_dir``.

    Requests are sent with :class:`~http.client.HTTPConnection` rather than a
    higher-level client so the raw request path reaches the handler untouched,
    which is what the directory-traversal tests need.
    """
    handler = partial(
        ViewerHandler, review_dir=review_dir.resolve(), patterns=REPORT_PATTERNS
    )
    server = ViewerServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    connection = HTTPConnection("127.0.0.1", server.server_address[1])
    yield connection

    connection.close()
    server.shutdown()
    server.server_close()
    thread.join()


def get(client: HTTPConnection, path: str):
    """Send a ``GET`` and return the response status and body."""
    client.request("GET", path)
    response = client.getresponse()
    return response.status, response.read()


def post(client: HTTPConnection, path: str, payload: dict):
    """Send a JSON ``POST`` and return the response status and decoded body."""
    client.request(
        "POST",
        path,
        body=json.dumps(payload),
        headers={"Content-Type": "application/json"},
    )
    response = client.getresponse()
    return response.status, json.loads(response.read())


class TestViewerPage:
    def test_ships_with_the_package(self):
        assert b"<title>MReyeXtract QC</title>" in server.viewer_page()

    def test_served_at_root(self, client: HTTPConnection):
        status, body = get(client, "/")
        assert status == 200
        assert b"MReyeXtract QC" in body


class TestReportIndex:
    def test_lists_reports_with_ratings(self, client: HTTPConnection):
        status, body = get(client, "/api/reports")
        index = json.loads(body)

        assert status == 200
        assert [report["relative_path"] for report in index["reports"]] == [
            "report_group.html",
            REPORT,
            "sub-01/func/sub-01_task-rest_run-2_desc-eye_report.html",
            "sub-02/func/sub-02_task-rest_run-1_desc-eye_report.html",
        ]
        assert all(
            report["rating"] == {"status": "unrated", "note": ""}
            for report in index["reports"]
        )

    def test_reports_the_ratings_file(self, client: HTTPConnection, review_dir: Path):
        _, body = get(client, "/api/reports")
        index = json.loads(body)

        assert index["review_dir"] == str(review_dir)
        assert index["ratings_path"] == str(ratings_path(review_dir))

    def test_picks_up_reports_written_while_serving(
        self, client: HTTPConnection, review_dir: Path
    ):
        (review_dir / "sub-03").mkdir()
        (review_dir / "sub-03" / "sub-03_desc-eye_report.html").write_text("<html>")

        _, body = get(client, "/api/reports")

        paths = [report["relative_path"] for report in json.loads(body)["reports"]]
        assert "sub-03/sub-03_desc-eye_report.html" in paths


class TestServeReport:
    def test_serves_the_html(self, client: HTTPConnection):
        status, body = get(client, f"/report/{REPORT}")

        assert status == 200
        assert REPORT.encode() in body

    def test_unknown_report_is_not_found(self, client: HTTPConnection):
        status, _ = get(client, "/report/sub-09/nope.html")
        assert status == 404

    def test_refuses_to_escape_the_review_directory(
        self, client: HTTPConnection, review_dir: Path
    ):
        secret = review_dir.parent.parent / "secret.txt"
        secret.write_text("private")

        status, _ = get(client, "/report/../../secret.txt")

        assert status == 404

    def test_refuses_an_absolute_path(self, client: HTTPConnection, review_dir: Path):
        secret = review_dir.parent.parent / "secret.txt"
        secret.write_text("private")

        status, _ = get(client, f"/report/{secret}")

        assert status == 404


class TestRating:
    def test_records_a_verdict(self, client: HTTPConnection, review_dir: Path):
        status, body = post(
            client,
            "/api/rating",
            {"path": REPORT, "status": "bad", "note": "  blurry "},
        )

        assert status == 200
        assert body == {"path": REPORT, "rating": {"status": "bad", "note": "blurry"}}
        assert read_ratings(ratings_path(review_dir)) == {
            REPORT: Rating(status=RatingStatus.BAD, note="blurry")
        }

    def test_verdict_shows_up_in_the_index(self, client: HTTPConnection):
        post(client, "/api/rating", {"path": REPORT, "status": "good"})

        _, body = get(client, "/api/reports")
        reports = {
            report["relative_path"]: report for report in json.loads(body)["reports"]
        }

        assert reports[REPORT]["rating"] == {"status": "good", "note": ""}

    def test_unknown_status_is_rejected(self, client: HTTPConnection, review_dir: Path):
        status, body = post(client, "/api/rating", {"path": REPORT, "status": "maybe"})

        assert status == 400
        assert "error" in body
        assert not ratings_path(review_dir).exists()

    def test_unknown_report_is_rejected(self, client: HTTPConnection):
        status, _ = post(client, "/api/rating", {"path": "nope.html", "status": "good"})
        assert status == 404

    def test_report_outside_the_review_directory_is_rejected(
        self, client: HTTPConnection, review_dir: Path
    ):
        secret = review_dir.parent.parent / "secret.txt"
        secret.write_text("private")

        status, _ = post(
            client, "/api/rating", {"path": "../../secret.txt", "status": "bad"}
        )

        assert status == 404

    def test_malformed_body_is_rejected(self, client: HTTPConnection):
        client.request(
            "POST",
            "/api/rating",
            body="not json",
            headers={"Content-Type": "application/json"},
        )
        assert client.getresponse().status == 400


class TestUnknownRoutes:
    def test_get(self, client: HTTPConnection):
        status, _ = get(client, "/nope")
        assert status == 404

    def test_post(self, client: HTTPConnection):
        status, _ = post(client, "/nope", {})
        assert status == 404


class TestViewerServer:
    def test_ignores_a_client_hanging_up(self, capsys):
        server = ViewerServer.__new__(ViewerServer)

        try:
            raise ConnectionResetError(54, "Connection reset by peer")
        except ConnectionResetError:
            server.handle_error(None, ("127.0.0.1", 1234))

        assert capsys.readouterr().err == ""

    def test_still_reports_real_failures(self, capsys):
        server = ViewerServer.__new__(ViewerServer)

        try:
            raise ValueError("something actually broke")
        except ValueError:
            server.handle_error(None, ("127.0.0.1", 1234))

        assert "something actually broke" in capsys.readouterr().err


class TestServeReports:
    def test_serves_until_interrupted(self, review_dir: Path, monkeypatch):
        served = {}

        def _fake_serve_forever(self, poll_interval=0.5):
            served["address"] = self.server_address
            raise KeyboardInterrupt

        monkeypatch.setattr(ViewerServer, "serve_forever", _fake_serve_forever)

        serve_reports(review_dir, port=0, open_browser=False)

        assert served["address"][0] == "127.0.0.1"

    def test_missing_directory_raises(self, tmp_path: Path):
        with pytest.raises(FileNotFoundError):
            serve_reports(tmp_path / "does_not_exist", open_browser=False)
