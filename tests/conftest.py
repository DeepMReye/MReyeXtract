"""Shared fixtures for the mreyextract test suite."""

import json
from pathlib import Path

import pytest


@pytest.fixture
def bids_root(tmp_path: Path) -> Path:
    """A minimal, valid-enough BIDS dataset with a single BOLD run.

    Returns the resolved dataset root so that ``relative_to`` operations in the
    code under test line up on platforms where ``tmp_path`` is a symlink.
    """
    root = (tmp_path / "bids").resolve()
    (root / "sub-01" / "func").mkdir(parents=True)

    (root / "dataset_description.json").write_text(
        json.dumps({"Name": "test", "BIDSVersion": "1.8.0"})
    )
    bold = root / "sub-01" / "func" / "sub-01_task-rest_run-1_bold.nii.gz"
    bold.write_bytes(b"")

    return root


@pytest.fixture
def fmriprep_root(tmp_path: Path) -> Path:
    """A BIDS dataset with an fMRIPrep pipeline under ``derivatives/fmriprep``.

    The derivative BOLD runs carry ``desc`` (and ``space``) entities so the
    derivatives branch of ``bids_paths`` and DESC_ADD appending can be exercised.
    Returns the resolved dataset root.
    """
    root = (tmp_path / "bids").resolve()
    deriv = root / "derivatives" / "fmriprep"
    func = deriv / "sub-01" / "func"
    func.mkdir(parents=True)  # also creates root and derivatives/fmriprep

    (root / "dataset_description.json").write_text(
        json.dumps({"Name": "raw", "BIDSVersion": "1.8.0"})
    )
    (deriv / "dataset_description.json").write_text(
        json.dumps(
            {
                "Name": "fMRIPrep",
                "BIDSVersion": "1.8.0",
                "GeneratedBy": [{"Name": "fmriprep"}],
            }
        )
    )

    for name in (
        "sub-01_task-rest_run-1_space-MNI152NLin2009cAsym_desc-preproc_bold.nii.gz",
        "sub-01_task-rest_run-1_desc-smoothed_bold.nii.gz",
        "sub-01_task-rest_run-1_bold.nii.gz",  # no desc
    ):
        (func / name).write_bytes(b"")

    return root


@pytest.fixture
def review_dir(tmp_path: Path) -> Path:
    """A derivatives tree of QC reports, as the viewer expects to find them.

    Covers both naming conventions (this package's and DeepMReye's), a report
    outside any ``sub-*`` directory, and files that must be ignored: non-reports,
    AppleDouble sidecars, and anything under a hidden directory.
    Returns the resolved directory to review.
    """
    root = (tmp_path / "derivatives" / "mreyextract").resolve()

    for name in (
        "sub-01/func/sub-01_task-rest_run-1_desc-eye_report.html",
        "sub-01/func/sub-01_task-rest_run-2_desc-eye_report.html",
        "sub-02/func/sub-02_task-rest_run-1_desc-eye_report.html",
        "report_group.html",
        "sub-01/func/._sub-01_task-rest_run-1_desc-eye_report.html",
        ".snapshot/sub-01/func/sub-01_task-rest_run-1_desc-eye_report.html",
    ):
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"<html><body>{name}</body></html>")

    (
        root / "sub-01" / "func" / "sub-01_task-rest_run-1_desc-eye_bold.nii.gz"
    ).write_bytes(b"")
    (root / "dataset_description.json").write_text("{}")

    return root


@pytest.fixture
def non_bids_root(tmp_path: Path) -> Path:
    """A plain (non-BIDS) tree containing NIfTI and non-NIfTI files."""
    root = (tmp_path / "raw").resolve()
    func = root / "sub-01" / "func"
    func.mkdir(parents=True)

    (func / "sub-01_task-rest_run-1_bold.nii.gz").write_bytes(b"")
    (func / "sub-01_task-rest_run-2_bold.nii").write_bytes(b"")
    # Non-NIfTI companions that must be ignored.
    (func / "sub-01_task-rest_run-1_bold.nii.json").write_text("{}")
    (func / "sub-01_task-rest_run-1_events.tsv").write_text("onset\n")

    return root
