"""Tests for :mod:`mreyextract.io`."""

import json
from pathlib import Path

import pytest

from mreyextract import io
from mreyextract.io import RunPaths, mreyextract_root


class TestRunPaths:
    def test_holds_three_paths(self):
        rp = RunPaths(
            in_path=Path("in.nii"),
            out_eye_path=Path("eye.nii"),
            out_report_path=Path("report.html"),
        )
        assert rp.in_path == Path("in.nii")
        assert rp.out_eye_path == Path("eye.nii")
        assert rp.out_report_path == Path("report.html")

    def test_equality(self):
        args = dict(
            in_path=Path("a"),
            out_eye_path=Path("b"),
            out_report_path=Path("c"),
        )
        assert RunPaths(**args) == RunPaths(**args)


class TestMreyextractRoot:
    def test_missing_root_raises(self, tmp_path: Path):
        with pytest.raises(FileNotFoundError):
            mreyextract_root(tmp_path / "does_not_exist")

    def test_creates_derivatives_tree(self, tmp_path: Path):
        deriv = mreyextract_root(tmp_path)
        assert deriv == tmp_path / "derivatives" / "mreyextract"
        assert deriv.is_dir()

    def test_accepts_str_root(self, tmp_path: Path):
        deriv = mreyextract_root(str(tmp_path))
        assert deriv.is_dir()

    def test_writes_dataset_description(self, tmp_path: Path):
        deriv = mreyextract_root(tmp_path)
        desc_path = deriv / "dataset_description.json"
        assert desc_path.is_file()

        desc = json.loads(desc_path.read_text())
        assert desc["Name"] == "MReyeXtract Outputs"
        assert desc["BIDSVersion"] == "1.8.0"
        assert desc["PipelineDescription"]["Name"] == "MReyeXtract"

    def test_idempotent_on_existing_tree(self, tmp_path: Path):
        first = mreyextract_root(tmp_path)
        # Should not raise even though the tree/description already exist.
        second = mreyextract_root(tmp_path)
        assert first == second


class TestWriteBidsDescription:
    def test_creates_file(self, tmp_path: Path):
        io._write_bids_description(tmp_path)
        assert (tmp_path / "dataset_description.json").is_file()

    def test_does_not_overwrite_existing(self, tmp_path: Path):
        desc_path = tmp_path / "dataset_description.json"
        desc_path.write_text(json.dumps({"Name": "custom"}))

        io._write_bids_description(tmp_path)

        # Existing content is preserved untouched.
        assert json.loads(desc_path.read_text()) == {"Name": "custom"}
