"""Tests for :mod:`mreyextract.viewer.reports`."""

import threading
from pathlib import Path

import pytest

from mreyextract.viewer.reports import (
    RATING_COLUMNS,
    Rating,
    RatingStatus,
    find_reports,
    rate_report,
    rate_reports,
    ratings_path,
    read_ratings,
    report_subject,
    write_ratings,
)


class TestReportSubject:
    def test_reads_subject_from_directory(self):
        assert report_subject("sub-01/func/sub-01_task-rest_report.html") == "01"

    def test_reads_alphanumeric_label(self):
        assert report_subject("sub-pilot2/report_sub-pilot2.html") == "pilot2"

    def test_unknown_without_entity(self):
        assert report_subject("report_group.html") == "unknown"


class TestFindReports:
    def test_missing_directory_raises(self, tmp_path: Path):
        with pytest.raises(FileNotFoundError):
            find_reports(tmp_path / "does_not_exist")

    def test_finds_both_naming_conventions(self, review_dir: Path):
        paths = [report.relative_path for report in find_reports(review_dir)]
        assert paths == [
            "report_group.html",
            "sub-01/func/sub-01_task-rest_run-1_desc-eye_report.html",
            "sub-01/func/sub-01_task-rest_run-2_desc-eye_report.html",
            "sub-02/func/sub-02_task-rest_run-1_desc-eye_report.html",
        ]

    def test_ignores_non_report_files(self, review_dir: Path):
        paths = [report.relative_path for report in find_reports(review_dir)]
        assert not any(path.endswith((".nii.gz", ".json")) for path in paths)

    def test_ignores_appledouble_sidecars(self, review_dir: Path):
        names = [Path(report.relative_path).name for report in find_reports(review_dir)]
        assert not any(name.startswith("._") for name in names)

    def test_ignores_hidden_directories(self, review_dir: Path):
        paths = [report.relative_path for report in find_reports(review_dir)]
        assert not any(path.startswith(".snapshot/") for path in paths)

    def test_labels_and_subjects(self, review_dir: Path):
        reports = {report.relative_path: report for report in find_reports(review_dir)}

        subject_report = reports[
            "sub-02/func/sub-02_task-rest_run-1_desc-eye_report.html"
        ]
        assert subject_report.label == "sub-02_task-rest_run-1_desc-eye_report"
        assert subject_report.subject == "02"
        assert reports["report_group.html"].subject == "unknown"

    def test_deduplicates_across_patterns(self, review_dir: Path):
        reports = find_reports(review_dir, patterns=("**/*_report.html", "**/*.html"))
        paths = [report.relative_path for report in reports]
        assert len(paths) == len(set(paths))

    def test_unrated_by_default(self, review_dir: Path):
        assert all(
            report.rating == Rating(status=RatingStatus.UNRATED)
            for report in find_reports(review_dir)
        )

    def test_attaches_recorded_ratings(self, review_dir: Path):
        rate_report(review_dir, "report_group.html", RatingStatus.BAD, note="clipped")

        reports = {report.relative_path: report for report in find_reports(review_dir)}
        assert reports["report_group.html"].rating == Rating(
            status=RatingStatus.BAD, note="clipped"
        )


class TestReadRatings:
    def test_missing_file_is_empty(self, tmp_path: Path):
        assert read_ratings(tmp_path / "qc_ratings.tsv") == {}

    def test_reads_rows_and_skips_header(self, tmp_path: Path):
        path = tmp_path / "qc_ratings.tsv"
        path.write_text("path\tstatus\tnote\na.html\tgood\t\nb.html\tbad\tmisaligned\n")

        assert read_ratings(path) == {
            "a.html": Rating(status=RatingStatus.GOOD),
            "b.html": Rating(status=RatingStatus.BAD, note="misaligned"),
        }

    def test_reads_legacy_flag_list(self, tmp_path: Path):
        path = tmp_path / "problematic_qc.txt"
        path.write_text("a.html\nb.html\n")

        assert read_ratings(path) == {
            "a.html": Rating(status=RatingStatus.BAD),
            "b.html": Rating(status=RatingStatus.BAD),
        }

    def test_unknown_status_raises(self, tmp_path: Path):
        path = tmp_path / "qc_ratings.tsv"
        path.write_text("path\tstatus\tnote\na.html\tmaybe\t\n")

        with pytest.raises(ValueError):
            read_ratings(path)


class TestWriteRatings:
    def test_writes_header_and_sorted_rows(self, tmp_path: Path):
        path = tmp_path / "qc_ratings.tsv"
        write_ratings(
            path,
            {
                "b.html": Rating(status=RatingStatus.BAD, note="misaligned"),
                "a.html": Rating(status=RatingStatus.GOOD),
            },
        )

        assert path.read_text().splitlines() == [
            "\t".join(RATING_COLUMNS),
            "a.html\tgood\t",
            "b.html\tbad\tmisaligned",
        ]

    def test_round_trips(self, tmp_path: Path):
        path = tmp_path / "qc_ratings.tsv"
        ratings = {"a.html": Rating(status=RatingStatus.GOOD, note="clean")}

        write_ratings(path, ratings)

        assert read_ratings(path) == ratings

    def test_leaves_no_temporary_file(self, tmp_path: Path):
        path = tmp_path / "qc_ratings.tsv"
        write_ratings(path, {"a.html": Rating(status=RatingStatus.GOOD)})

        assert [child.name for child in tmp_path.iterdir()] == ["qc_ratings.tsv"]


class TestRateReport:
    def test_writes_into_review_directory(self, review_dir: Path):
        rate_report(review_dir, "report_group.html", RatingStatus.GOOD)

        assert ratings_path(review_dir) == review_dir / "qc_ratings.tsv"
        assert read_ratings(ratings_path(review_dir)) == {
            "report_group.html": Rating(status=RatingStatus.GOOD)
        }

    def test_overwrites_previous_verdict(self, review_dir: Path):
        rate_report(review_dir, "report_group.html", RatingStatus.GOOD)
        rating = rate_report(review_dir, "report_group.html", RatingStatus.BAD)

        assert rating == Rating(status=RatingStatus.BAD)
        assert read_ratings(ratings_path(review_dir)) == {
            "report_group.html": Rating(status=RatingStatus.BAD)
        }

    def test_unrated_drops_the_row(self, review_dir: Path):
        rate_report(review_dir, "report_group.html", RatingStatus.GOOD)
        rate_report(review_dir, "report_group.html", RatingStatus.UNRATED)

        assert read_ratings(ratings_path(review_dir)) == {}

    def test_unrated_with_note_is_kept(self, review_dir: Path):
        rate_report(
            review_dir, "report_group.html", RatingStatus.UNRATED, note="ask Zach"
        )

        assert read_ratings(ratings_path(review_dir)) == {
            "report_group.html": Rating(status=RatingStatus.UNRATED, note="ask Zach")
        }

    def test_collapses_whitespace_in_note(self, review_dir: Path):
        rating = rate_report(
            review_dir, "report_group.html", RatingStatus.BAD, note="eye\tcut\noff"
        )

        assert rating.note == "eye cut off"
        assert read_ratings(ratings_path(review_dir))["report_group.html"] == rating

    def test_batch_is_written_in_one_pass(self, review_dir: Path):
        stored = rate_reports(
            review_dir,
            {
                "report_group.html": Rating(status=RatingStatus.GOOD),
                "sub-01_report.html": Rating(
                    status=RatingStatus.BAD, note="eye\tcut off"
                ),
            },
        )

        assert stored["sub-01_report.html"].note == "eye cut off"
        assert read_ratings(ratings_path(review_dir)) == {
            "report_group.html": Rating(status=RatingStatus.GOOD),
            "sub-01_report.html": Rating(status=RatingStatus.BAD, note="eye cut off"),
        }

    def test_batch_can_clear_and_set_together(self, review_dir: Path):
        rate_report(review_dir, "report_group.html", RatingStatus.GOOD)

        rate_reports(
            review_dir,
            {
                "report_group.html": Rating(status=RatingStatus.UNRATED),
                "sub-01_report.html": Rating(status=RatingStatus.BAD),
            },
        )

        assert read_ratings(ratings_path(review_dir)) == {
            "sub-01_report.html": Rating(status=RatingStatus.BAD)
        }

    def test_overlapping_verdicts_are_all_kept(self, review_dir: Path):
        # The viewer rates on a background request per keypress, so held keys
        # and notes saved on top of a verdict overlap these read-modify-writes.
        paths = [f"sub-{index:02d}_desc-eye_report.html" for index in range(40)]
        barrier = threading.Barrier(len(paths))

        def worker(relative_path):
            barrier.wait()
            rate_report(review_dir, relative_path, RatingStatus.GOOD)

        threads = [threading.Thread(target=worker, args=(path,)) for path in paths]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        assert sorted(read_ratings(ratings_path(review_dir))) == sorted(paths)

    def test_leaves_no_temporary_files_behind(self, review_dir: Path):
        barrier = threading.Barrier(8)

        def worker(index):
            barrier.wait()
            rate_report(review_dir, f"report_{index}.html", RatingStatus.BAD)

        threads = [threading.Thread(target=worker, args=(index,)) for index in range(8)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        assert list(review_dir.glob("*.tmp")) == []

    def test_keeps_verdicts_written_by_someone_else(self, review_dir: Path):
        rate_report(review_dir, "report_group.html", RatingStatus.GOOD)

        # A second reviewer's verdict lands in the file between our two writes.
        ratings = read_ratings(ratings_path(review_dir))
        ratings["sub-01/func/sub-01_task-rest_run-1_desc-eye_report.html"] = Rating(
            status=RatingStatus.BAD
        )
        write_ratings(ratings_path(review_dir), ratings)

        rate_report(review_dir, "report_group.html", RatingStatus.BAD)

        assert read_ratings(ratings_path(review_dir)) == {
            "report_group.html": Rating(status=RatingStatus.BAD),
            "sub-01/func/sub-01_task-rest_run-1_desc-eye_report.html": Rating(
                status=RatingStatus.BAD
            ),
        }
