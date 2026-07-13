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
