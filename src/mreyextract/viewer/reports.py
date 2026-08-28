"""
Quality-control reports and the ratings a reviewer gives them
"""

import logging
import os
import re
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path

logger = logging.getLogger(__name__)

# Matches the reports written by this package (sub-01_task-rest_desc-eye_report
# .html) as well as those written by DeepMReye (report_sub-01.html), so a
# dataset processed with either can be reviewed with the same command.
REPORT_PATTERNS = ("**/*_report.html", "**/report_*.html")

# Written into the directory being reviewed, so the verdicts sit alongside the
# reports and eye voxels they describe.
RATINGS_NAME = "qc_ratings.tsv"

RATING_COLUMNS = ("path", "status", "note")

# The viewer groups its report list by subject; everything else it needs is in
# the path itself, so this is the only entity worth pulling out of a filename.
SUBJECT_PATTERN = re.compile(r"sub-([a-zA-Z0-9]+)")

UNKNOWN_SUBJECT = "unknown"

# Directories listed at once while searching for reports. Sized for round-trip
# latency rather than for cores: the walk spends its time waiting on a mount,
# not computing.
SCAN_WORKERS = 16

# The viewer answers each request on its own thread, so a held-down rating key
# or a note saved on top of a verdict puts several read-modify-writes of the
# ratings file in flight at once. Serialising them is what keeps one from
# overwriting the other -- a lost verdict is the failure a reviewer cannot see,
# since both writes are reported as successful. Covers this process only.
_RATINGS_LOCK = threading.Lock()


class RatingStatus(StrEnum):
    """
    Verdict a reviewer can give a quality-control report.
    """

    GOOD = "good"
    BAD = "bad"
    UNRATED = "unrated"


@dataclass
class Rating:
    """
    A reviewer's verdict on a single report, and one row of the ratings file.

    Ratings are stored apart from the reports they describe: reports are
    regenerated whenever extraction is re-run with ``--force``, while the
    verdicts have to survive that and stay readable afterwards as a table.

    Parameters
    ----------
    status : RatingStatus, optional
        Whether the report was marked good, bad, or left unrated. Default
        ``UNRATED``.
    note : str, optional
        Free-text note. Default empty.
    """

    status: RatingStatus = RatingStatus.UNRATED
    note: str = ""


@dataclass
class Report:
    """
    A quality-control report found underneath a review directory.

    Parameters
    ----------
    relative_path : str
        POSIX path of the report relative to the review directory. This is the
        identifier the viewer addresses reports by and the key written to the
        ratings file, so ratings survive the dataset being moved or re-mounted.
    label : str
        Report filename without its ``.html`` extension.
    subject : str
        Subject the report belongs to, used to group the viewer's report list.
    rating : Rating, optional
        The verdict currently recorded for this report. Default unrated.
    """

    relative_path: str
    label: str
    subject: str
    rating: Rating = field(default_factory=Rating)


def ratings_path(review_dir: Path | str) -> Path:
    """
    Locate the ratings file for a review directory.

    Parameters
    ----------
    review_dir : Path | str
        Directory the reports are read from, e.g. the output of
        :func:`~mreyextract.io.mreyextract_root`.

    Returns
    -------
    Path
        ``<review_dir>/qc_ratings.tsv``.
    """
    return Path(review_dir) / RATINGS_NAME


def report_subject(relative_path: str) -> str:
    """
    Read the subject label out of a report path.

    Parameters
    ----------
    relative_path : str
        POSIX path such as ``sub-01/func/sub-01_task-rest_desc-eye_report.html``.

    Returns
    -------
    str
        The subject label, or ``"unknown"`` for a path without a ``sub-`` entity
        (reports from a non-BIDS tree), so those still group together.
    """
    match = SUBJECT_PATTERN.search(relative_path)
    return match.group(1) if match else UNKNOWN_SUBJECT


def _glob_regex(pattern: str) -> re.Pattern:
    """
    Compile a glob over relative paths into a regular expression.

    Matching is done against paths this package has already read from a single
    walk of the tree, rather than by handing each pattern to ``Path.glob`` and
    walking again per pattern.

    Parameters
    ----------
    pattern : str
        Glob relative to the review directory, e.g. ``"**/*_report.html"``.
        ``**`` stands for any number of directories, ``*`` and ``?`` do not
        cross a directory boundary.

    Returns
    -------
    re.Pattern
        Expression matching a whole POSIX relative path.
    """
    parts = []
    segments = pattern.split("/")
    for index, segment in enumerate(segments):
        if segment == "**":
            parts.append("(?:[^/]+/)*")
            continue

        expression = "".join(
            "[^/]*" if char == "*" else "[^/]" if char == "?" else re.escape(char)
            for char in segment
        )
        separator = "" if index == len(segments) - 1 else "/"
        parts.append(expression + separator)

    return re.compile("".join(parts) + r"\Z")


def _scan_directory(directory: Path) -> tuple[list[Path], list[Path]]:
    """
    List one directory, separating files from directories to descend into.

    Entries beginning with a dot are skipped here rather than filtered later, so
    the walk never descends into a hidden tree at all -- a mount's ``.snapshot``
    directory holds a full copy of the dataset per snapshot, and walking those
    can cost more than the dataset itself.

    Parameters
    ----------
    directory : Path
        Directory to list.

    Returns
    -------
    tuple[list[Path], list[Path]]
        The files found, and the subdirectories to walk next. A directory that
        cannot be read is logged and treated as empty.
    """
    files = []
    directories = []

    try:
        with os.scandir(directory) as entries:
            for entry in entries:
                if entry.name.startswith("."):
                    continue
                # Symlinked directories are not followed, which keeps a link
                # pointing back up the tree from looping forever.
                if entry.is_dir(follow_symlinks=False):
                    directories.append(Path(entry.path))
                elif entry.is_file():
                    files.append(Path(entry.path))
    except OSError as error:
        logger.warning("Could not read %s: %s", directory, error)

    return files, directories


def _scan_tree(root: Path, workers: int = SCAN_WORKERS) -> list[Path]:
    """
    Walk a directory tree, listing sibling directories concurrently.

    Every listing of a directory on a network mount is a round-trip, and the
    reviewer waits through all of them before the first report appears. The
    walk is pure IO wait, so listing a whole level of the tree at once cuts that
    wait roughly by the number of workers.

    Parameters
    ----------
    root : Path
        Directory to walk.
    workers : int, optional
        Directories to list concurrently. Default :data:`SCAN_WORKERS`.

    Returns
    -------
    list[Path]
        Every file in the tree, excluding hidden entries and anything beneath
        a hidden directory.
    """
    files: list[Path] = []
    level = [root]

    with ThreadPoolExecutor(max_workers=workers) as pool:
        while level:
            next_level: list[Path] = []
            for found_files, found_directories in pool.map(_scan_directory, level):
                files.extend(found_files)
                next_level.extend(found_directories)
            level = next_level

    return files


def find_reports(
    review_dir: Path | str,
    patterns: tuple[str, ...] | list[str] | None = None,
) -> list[Report]:
    """
    Search a directory tree for quality-control reports and attach their ratings.

    The tree is walked once and each file tested against every pattern, so
    adding a pattern costs no extra IO.

    Parameters
    ----------
    review_dir : Path | str
        Directory to search, typically the output of
        :func:`~mreyextract.io.mreyextract_root`.
    patterns : tuple[str, ...] | list[str] | None, optional
        Globs, relative to ``review_dir``, selecting report files. Default
        :data:`REPORT_PATTERNS`, which matches this package's and DeepMReye's
        naming.

    Returns
    -------
    list[Report]
        The reports found, de-duplicated across patterns and sorted by path.
        Reports with no recorded verdict carry an unrated :class:`Rating`.

    Raises
    ------
    FileNotFoundError
        If ``review_dir`` does not exist.
    """
    review_dir = Path(review_dir)
    if not review_dir.is_dir():
        raise FileNotFoundError(f"Could not find report directory {review_dir}")

    if patterns is None:
        patterns = REPORT_PATTERNS

    matchers = [_glob_regex(pattern) for pattern in patterns]
    ratings = read_ratings(ratings_path(review_dir))

    reports: dict[str, Report] = {}
    for path in _scan_tree(review_dir):
        relative_path = path.relative_to(review_dir).as_posix()
        if not any(matcher.match(relative_path) for matcher in matchers):
            continue

        reports[relative_path] = Report(
            relative_path=relative_path,
            label=path.name.removesuffix(".html"),
            subject=report_subject(relative_path),
            rating=ratings.get(relative_path, Rating()),
        )

        logger.debug("Found report %s", relative_path)

    return [reports[relative_path] for relative_path in sorted(reports)]


def read_ratings(path: Path | str) -> dict[str, Rating]:
    """
    Read the tab-separated ratings file written by the viewer.

    A missing file reads as an empty set of ratings, so a review can start
    without any setup. A row holding only a path is read as a flagged report,
    which keeps hand-written or legacy one-path-per-line flag lists usable.

    Parameters
    ----------
    path : Path | str
        Ratings file to read.

    Returns
    -------
    dict[str, Rating]
        Report path (relative to the review directory) to its rating.

    Raises
    ------
    ValueError
        If a row carries a status that is not a :class:`RatingStatus`.
    """
    path = Path(path)
    if not path.exists():
        return {}

    ratings: dict[str, Rating] = {}
    for index, line in enumerate(path.read_text(encoding="utf-8").splitlines()):
        if not line.strip():
            continue

        fields = line.split("\t")
        if index == 0 and fields[0] == RATING_COLUMNS[0]:
            continue

        relative_path = fields[0].strip()
        if len(fields) == 1:
            ratings[relative_path] = Rating(status=RatingStatus.BAD)
            continue

        try:
            status = RatingStatus(fields[1].strip().lower())
        except ValueError as err:
            raise ValueError(
                f"Unknown status {fields[1]!r} for {relative_path} in {path}"
            ) from err

        note = fields[2].strip() if len(fields) > 2 else ""
        ratings[relative_path] = Rating(status=status, note=note)

    return ratings


def write_ratings(path: Path | str, ratings: dict[str, Rating]) -> None:
    """
    Write ratings to a tab-separated file, sorted by report path.

    The rows go to a temporary file that is then moved into place, so an
    interrupted save cannot leave a reviewer with a truncated set of ratings.

    Parameters
    ----------
    path : Path | str
        Ratings file to write. Parent directories are created if needed.
    ratings : dict[str, Rating]
        Report path (relative to the review directory) to its rating.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    rows = ["\t".join(RATING_COLUMNS)]
    for relative_path in sorted(ratings):
        rating = ratings[relative_path]
        rows.append("\t".join((relative_path, rating.status, rating.note)))

    # The temporary name carries the writer's identity: sharing one name lets a
    # concurrent writer move this file away before it can be renamed into place.
    tmp_path = path.with_name(f"{path.name}.{os.getpid()}.{threading.get_ident()}.tmp")
    tmp_path.write_text("\n".join(rows) + "\n", encoding="utf-8")
    os.replace(tmp_path, path)


def rate_reports(
    review_dir: Path | str, verdicts: dict[str, Rating]
) -> dict[str, Rating]:
    """
    Record a batch of verdicts in a review directory's ratings file.

    The whole batch costs one read-modify-write. Rating is a per-keypress
    action, but the file it writes may sit on a network mount where a single
    write is slow enough that a reviewer working quickly would otherwise queue
    up behind their own earlier verdicts, so the viewer sends everything that
    accumulated while the last write was in flight as one call.

    Parameters
    ----------
    review_dir : Path | str
        Directory being reviewed; its ratings file is updated.
    verdicts : dict[str, Rating]
        Report path (relative to ``review_dir``) to the verdict to record. A
        verdict of ``UNRATED`` with no note drops the report from the file.

    Returns
    -------
    dict[str, Rating]
        The verdicts as stored, with notes normalised.
    """
    stored = {
        relative_path: Rating(status=rating.status, note=" ".join(rating.note.split()))
        for relative_path, rating in verdicts.items()
    }

    path = ratings_path(review_dir)
    with _RATINGS_LOCK:
        ratings = read_ratings(path)
        for relative_path, rating in stored.items():
            if rating.status is RatingStatus.UNRATED and not rating.note:
                ratings.pop(relative_path, None)
            else:
                ratings[relative_path] = rating
        write_ratings(path, ratings)

    for relative_path, rating in stored.items():
        logger.info("Rated %s as %s", relative_path, rating.status)

    return stored


def rate_report(
    review_dir: Path | str,
    relative_path: str,
    status: RatingStatus,
    note: str = "",
) -> Rating:
    """
    Record one verdict in a review directory's ratings file.

    The file is re-read before it is rewritten, so two reviewers working through
    the same dataset (or an editor left open on the TSV) see each other's
    verdicts instead of silently overwriting them. Within one process that
    read-modify-write is serialised, so overlapping calls cannot lose a verdict;
    across processes it stays a last-writer-wins race on a narrow window.

    Parameters
    ----------
    review_dir : Path | str
        Directory being reviewed; its ratings file is updated.
    relative_path : str
        Report path relative to ``review_dir``.
    status : RatingStatus
        Verdict to record. ``UNRATED`` drops the report from the file unless a
        note is kept with it.
    note : str, optional
        Free-text note. Whitespace is collapsed, since tabs and newlines would
        break the row the note is written into.

    Returns
    -------
    Rating
        The rating as stored.
    """
    verdict = Rating(status=status, note=note)
    return rate_reports(review_dir, {relative_path: verdict})[relative_path]
