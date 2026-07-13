"""Tests for :mod:`mreyextract.extract`."""

from pathlib import Path

import pytest

from mreyextract import extract
from mreyextract.io import RunPaths


# ---------------------------------------------------------------------------
# strip_nifti_ext
# ---------------------------------------------------------------------------
class TestStripNiftiExt:
    @pytest.mark.parametrize(
        "name, expected",
        [
            ("sub-01_bold.nii", "sub-01_bold"),
            ("sub-01_bold.nii.gz", "sub-01_bold"),
            ("a.b.c.nii.gz", "a.b.c"),
        ],
    )
    def test_strips_known_extensions(self, name, expected):
        assert extract.strip_nifti_ext(name) == expected

    @pytest.mark.parametrize("name", ["foo.txt", "bold", "image.gz", "x.nii.bak"])
    def test_rejects_non_nifti(self, name):
        with pytest.raises(ValueError, match="Not a NIfTI filename"):
            extract.strip_nifti_ext(name)


# ---------------------------------------------------------------------------
# non_bids_paths
# ---------------------------------------------------------------------------
class TestNonBidsPaths:
    def test_finds_nifti_files(self, non_bids_root: Path, tmp_path: Path):
        out_dir = (tmp_path / "out").resolve()
        run_paths = extract.non_bids_paths(
            root=non_bids_root,
            glob_pattern="sub-*/**/func/*_bold.nii*",
            output_dir=out_dir,
        )
        names = sorted(p.in_path.name for p in run_paths)
        assert names == [
            "sub-01_task-rest_run-1_bold.nii.gz",
            "sub-01_task-rest_run-2_bold.nii",
        ]

    def test_ignores_non_nifti_matches(self, non_bids_root: Path, tmp_path: Path):
        out_dir = (tmp_path / "out").resolve()
        run_paths = extract.non_bids_paths(
            root=non_bids_root,
            glob_pattern="sub-*/**/func/*",  # matches .json / .tsv too
            output_dir=out_dir,
        )
        for rp in run_paths:
            assert rp.in_path.name.endswith((".nii", ".nii.gz"))

    def test_output_paths_mirror_input_layout(
        self, non_bids_root: Path, tmp_path: Path
    ):
        out_dir = (tmp_path / "out").resolve()
        run_paths = extract.non_bids_paths(
            root=non_bids_root,
            glob_pattern="sub-*/**/func/*_bold.nii.gz",
            output_dir=out_dir,
        )
        rp = run_paths[0]
        rel = rp.out_eye_path.relative_to(out_dir)
        assert rel == Path("sub-01/func/sub-01_task-rest_run-1_bold_desc-eye.nii.gz")
        assert rp.out_report_path.name == (
            "sub-01_task-rest_run-1_bold_desc-eye_report.html"
        )

    def test_pickle_extension(self, non_bids_root: Path, tmp_path: Path):
        out_dir = (tmp_path / "out").resolve()
        run_paths = extract.non_bids_paths(
            root=non_bids_root,
            glob_pattern="sub-*/**/func/*_bold.nii.gz",
            output_dir=out_dir,
            as_pickle=True,
        )
        assert run_paths[0].out_eye_path.name.endswith("_desc-eye.p")

    def test_skips_existing_without_force(self, non_bids_root: Path, tmp_path: Path):
        out_dir = (tmp_path / "out").resolve()
        # Precompute the expected output and create it.
        run_paths = extract.non_bids_paths(
            root=non_bids_root,
            glob_pattern="sub-*/**/func/*_bold.nii.gz",
            output_dir=out_dir,
        )
        existing = run_paths[0].out_eye_path
        existing.parent.mkdir(parents=True, exist_ok=True)
        existing.write_bytes(b"")

        again = extract.non_bids_paths(
            root=non_bids_root,
            glob_pattern="sub-*/**/func/*_bold.nii.gz",
            output_dir=out_dir,
        )
        assert existing not in [rp.out_eye_path for rp in again]

    def test_force_includes_existing(self, non_bids_root: Path, tmp_path: Path):
        out_dir = (tmp_path / "out").resolve()
        run_paths = extract.non_bids_paths(
            root=non_bids_root,
            glob_pattern="sub-*/**/func/*_bold.nii.gz",
            output_dir=out_dir,
        )
        existing = run_paths[0].out_eye_path
        existing.parent.mkdir(parents=True, exist_ok=True)
        existing.write_bytes(b"")

        forced = extract.non_bids_paths(
            root=non_bids_root,
            glob_pattern="sub-*/**/func/*_bold.nii.gz",
            output_dir=out_dir,
            force=True,
        )
        assert existing in [rp.out_eye_path for rp in forced]

    def test_does_not_reingest_output_dir(self, non_bids_root: Path):
        # Put the output dir inside the search root so its files could be globbed.
        out_dir = (non_bids_root / "derivatives" / "mreyextract").resolve()
        out_file = out_dir / "sub-01" / "func" / "already_bold.nii.gz"
        out_file.parent.mkdir(parents=True)
        out_file.write_bytes(b"")

        run_paths = extract.non_bids_paths(
            root=non_bids_root,
            glob_pattern="**/*_bold.nii*",
            output_dir=out_dir,
        )
        assert run_paths  # the real input files are still picked up
        for rp in run_paths:
            assert out_dir not in rp.in_path.parents

    def test_collision_raises(self, tmp_path: Path):
        # ``a.nii`` and ``a.nii.gz`` share a stem and collide on one output.
        root = (tmp_path / "raw").resolve()
        root.mkdir()
        (root / "a_bold.nii").write_bytes(b"")
        (root / "a_bold.nii.gz").write_bytes(b"")

        with pytest.raises(ValueError, match="Collision"):
            extract.non_bids_paths(
                root=root,
                glob_pattern="*_bold.nii*",
                output_dir=(tmp_path / "out").resolve(),
            )

    def test_no_matches_returns_empty(self, tmp_path: Path):
        empty = (tmp_path / "empty").resolve()
        empty.mkdir()
        run_paths = extract.non_bids_paths(
            root=empty,
            glob_pattern="**/*_bold.nii*",
            output_dir=(tmp_path / "out").resolve(),
        )
        assert run_paths == []


# ---------------------------------------------------------------------------
# make_layout
# ---------------------------------------------------------------------------
class TestMakeLayout:
    def test_builds_layout_for_root(self, bids_root: Path):
        layout = extract.make_layout(root=bids_root, derivatives_dir=None)
        bold = layout.get(suffix="bold", extension=[".nii", ".nii.gz"])
        assert len(bold) == 1

    def test_missing_target_raises(self, tmp_path: Path):
        with pytest.raises(FileNotFoundError):
            extract.make_layout(root=tmp_path / "nope", derivatives_dir=None)

    def test_missing_derivatives_dir_raises(self, bids_root: Path):
        with pytest.raises(FileNotFoundError):
            extract.make_layout(root=bids_root, derivatives_dir="fmriprep")


# ---------------------------------------------------------------------------
# bids_paths
# ---------------------------------------------------------------------------
class TestBidsPaths:
    def test_builds_run_paths(self, bids_root: Path, tmp_path: Path):
        out_dir = (tmp_path / "out").resolve()
        run_paths = extract.bids_paths(
            root=bids_root, derivatives_dir=None, output_dir=out_dir
        )
        assert len(run_paths) == 1
        rp = run_paths[0]
        assert rp.in_path.name == "sub-01_task-rest_run-1_bold.nii.gz"
        assert rp.out_eye_path.relative_to(out_dir) == Path(
            "sub-01/func/sub-01_task-rest_run-1_desc-eye_bold.nii.gz"
        )
        assert rp.out_report_path.name == (
            "sub-01_task-rest_run-1_desc-eye_report.html"
        )

    def test_pickle_suffix_and_extension(self, bids_root: Path, tmp_path: Path):
        out_dir = (tmp_path / "out").resolve()
        run_paths = extract.bids_paths(
            root=bids_root, derivatives_dir=None, output_dir=out_dir, as_pickle=True
        )
        assert run_paths[0].out_eye_path.name.endswith("_desc-eye_timeseries.p")

    def test_filters_select_files(self, bids_root: Path, tmp_path: Path):
        out_dir = (tmp_path / "out").resolve()
        matched = extract.bids_paths(
            root=bids_root,
            derivatives_dir=None,
            output_dir=out_dir,
            filters={"task": "rest"},
        )
        assert len(matched) == 1

        none = extract.bids_paths(
            root=bids_root,
            derivatives_dir=None,
            output_dir=out_dir,
            filters={"task": "nonexistent"},
        )
        assert none == []

    def test_skips_existing_without_force(self, bids_root: Path, tmp_path: Path):
        out_dir = (tmp_path / "out").resolve()
        run_paths = extract.bids_paths(
            root=bids_root, derivatives_dir=None, output_dir=out_dir
        )
        existing = run_paths[0].out_eye_path
        existing.parent.mkdir(parents=True, exist_ok=True)
        existing.write_bytes(b"")

        again = extract.bids_paths(
            root=bids_root, derivatives_dir=None, output_dir=out_dir
        )
        assert again == []

        forced = extract.bids_paths(
            root=bids_root, derivatives_dir=None, output_dir=out_dir, force=True
        )
        assert len(forced) == 1


# ---------------------------------------------------------------------------
# extract_eyeball_voxels (orchestration, with preprocess mocked out)
# ---------------------------------------------------------------------------
@pytest.fixture
def fake_masks(monkeypatch):
    """Stub ``preprocess.get_masks`` and record ``extract_mask`` calls."""
    masks = tuple(f"m{i}" for i in range(7))
    monkeypatch.setattr(extract.preprocess, "get_masks", lambda: masks)

    calls = []

    def _fake_extract_mask(run_path, *args, **kwargs):
        calls.append((run_path, args, kwargs))

    monkeypatch.setattr(extract.preprocess, "extract_mask", _fake_extract_mask)
    return calls


class TestExtractEyeballVoxels:
    def test_bids_path_processes_each_run(
        self, bids_root: Path, fake_masks
    ):
        extract.extract_eyeball_voxels(
            root=bids_root,
            glob_pattern="unused",
            bids_compatible=True,
            force=True,
        )
        assert len(fake_masks) == 1
        run_path, _, kwargs = fake_masks[0]
        assert isinstance(run_path, RunPaths)
        # Output directory is created before processing.
        assert run_path.out_eye_path.parent.is_dir()
        assert kwargs.get("as_pickle") is False

    def test_non_bids_path_processes_each_run(
        self, non_bids_root: Path, fake_masks
    ):
        extract.extract_eyeball_voxels(
            root=non_bids_root,
            glob_pattern="sub-*/**/func/*_bold.nii*",
            bids_compatible=False,
            force=True,
        )
        assert len(fake_masks) == 2

    def test_no_runs_skips_mask_loading(self, tmp_path: Path, monkeypatch):
        empty = (tmp_path / "empty").resolve()
        empty.mkdir()

        called = {"get_masks": False}

        def _boom():
            called["get_masks"] = True
            raise AssertionError("get_masks should not be called")

        monkeypatch.setattr(extract.preprocess, "get_masks", _boom)

        extract.extract_eyeball_voxels(
            root=empty,
            glob_pattern="**/*_bold.nii*",
            bids_compatible=False,
        )
        assert called["get_masks"] is False


# ---------------------------------------------------------------------------
# cli_main
# ---------------------------------------------------------------------------
class TestCliMain:
    def test_parses_args_and_dispatches(self, monkeypatch, tmp_path: Path):
        captured = {}

        def _fake_extract(**kwargs):
            captured.update(kwargs)

        monkeypatch.setattr(extract, "extract_eyeball_voxels", _fake_extract)
        monkeypatch.setattr(
            "sys.argv",
            [
                "mreyextract",
                "--root",
                str(tmp_path),
                "--task",
                "rest",
                "--force",
                "--as-pickle",
            ],
        )

        extract.cli_main()

        assert captured["root"] == str(tmp_path)
        assert captured["force"] is True
        assert captured["as_pickle"] is True
        assert captured["filters"]["task"] == ["rest"]

    def test_bids_filter_file_merged(self, monkeypatch, tmp_path: Path):
        captured = {}
        monkeypatch.setattr(
            extract, "extract_eyeball_voxels", lambda **kw: captured.update(kw)
        )

        filter_file = tmp_path / "filters.json"
        filter_file.write_text('{"session": "01"}')

        monkeypatch.setattr(
            "sys.argv",
            [
                "mreyextract",
                "--root",
                str(tmp_path),
                "--bids-filter-file",
                str(filter_file),
            ],
        )

        extract.cli_main()
        assert captured["filters"]["session"] == "01"

    def test_entity_value_conversions(self, monkeypatch, tmp_path: Path):
        from bids.layout import Query

        captured = {}
        monkeypatch.setattr(
            extract, "extract_eyeball_voxels", lambda **kw: captured.update(kw)
        )
        monkeypatch.setattr(
            "sys.argv",
            [
                "mreyextract",
                "--root",
                str(tmp_path),
                "--subject",
                "sub-01",  # prefix stripped -> "01"
                "--session",
                "none",  # -> Query.NONE
                "--task",
                "*",  # -> Query.ANY
                "--run",
                "3",  # int-typed
            ],
        )

        extract.cli_main()

        filters = captured["filters"]
        assert filters["subject"] == ["01"]
        assert filters["session"] == [Query.NONE]
        assert filters["task"] == [Query.ANY]
        assert filters["run"] == [3]

    def test_root_is_required(self, monkeypatch):
        monkeypatch.setattr("sys.argv", ["mreyextract"])
        with pytest.raises(SystemExit):
            extract.cli_main()
