"""Tests for :mod:`mreyextract.extract`."""

import os
from pathlib import Path

import pytest

from mreyextract import extract
from mreyextract.io import RunPaths


class _FakeParallel:
    """Stand-in for ``joblib.Parallel`` that runs delayed tasks in-process.

    Keeps ``preprocess`` mocks (which only apply to the current process) in
    effect, so the parallel dispatch path is exercised without spawning workers.
    """

    def __init__(self, **kwargs):
        self.kwargs = kwargs

    def __call__(self, tasks):
        return [func(*args, **kw) for func, args, kw in tasks]


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
    def test_bids_path_processes_each_run(self, bids_root: Path, fake_masks):
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

    def test_non_bids_path_processes_each_run(self, non_bids_root: Path, fake_masks):
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

    def test_threads_per_job_sets_env(self, bids_root: Path, fake_masks, monkeypatch):
        monkeypatch.delenv("ITK_GLOBAL_DEFAULT_NUMBER_OF_THREADS", raising=False)
        extract.extract_eyeball_voxels(
            root=bids_root,
            glob_pattern="unused",
            bids_compatible=True,
            force=True,
            threads_per_job=3,
        )
        assert os.environ["ITK_GLOBAL_DEFAULT_NUMBER_OF_THREADS"] == "3"

    def test_auto_threads_split_uses_allocation(
        self, bids_root: Path, fake_masks, monkeypatch
    ):
        # Pretend the allocation (cgroup/affinity) exposes 8 CPUs.
        monkeypatch.setattr(extract, "loky_cpu_count", lambda: 8)
        monkeypatch.setattr(extract, "Parallel", _FakeParallel)
        monkeypatch.delenv("ITK_GLOBAL_DEFAULT_NUMBER_OF_THREADS", raising=False)

        extract.extract_eyeball_voxels(
            root=bids_root,
            glob_pattern="unused",
            bids_compatible=True,
            force=True,
            n_jobs=2,  # 8 // 2 -> 4 threads per job
        )
        assert os.environ["ITK_GLOBAL_DEFAULT_NUMBER_OF_THREADS"] == "4"

    def test_auto_threads_all_cores_when_serial(
        self, bids_root: Path, fake_masks, monkeypatch
    ):
        monkeypatch.setattr(extract, "loky_cpu_count", lambda: 8)
        monkeypatch.delenv("ITK_GLOBAL_DEFAULT_NUMBER_OF_THREADS", raising=False)

        extract.extract_eyeball_voxels(
            root=bids_root,
            glob_pattern="unused",
            bids_compatible=True,
            force=True,
            n_jobs=1,  # serial -> a single job may use all allocated cores
        )
        assert os.environ["ITK_GLOBAL_DEFAULT_NUMBER_OF_THREADS"] == "8"

    def test_parallel_dispatches_all_runs(
        self, non_bids_root: Path, fake_masks, monkeypatch
    ):
        monkeypatch.setattr(extract, "Parallel", _FakeParallel)
        extract.extract_eyeball_voxels(
            root=non_bids_root,
            glob_pattern="sub-*/**/func/*_bold.nii*",
            bids_compatible=False,
            force=True,
            n_jobs=2,
        )
        # Both independent runs were dispatched through the parallel path.
        assert len(fake_masks) == 2


class TestProcessRun:
    def test_creates_output_dir_and_extracts(self, tmp_path: Path, monkeypatch):
        monkeypatch.setattr(extract, "_cached_masks", lambda: tuple(range(7)))

        calls = []
        monkeypatch.setattr(
            extract.preprocess,
            "extract_mask",
            lambda run_path, *a, **kw: calls.append((run_path, kw)),
        )

        rp = RunPaths(
            in_path=tmp_path / "in.nii.gz",
            out_eye_path=tmp_path / "sub-01" / "func" / "out_desc-eye.nii.gz",
            out_report_path=tmp_path / "sub-01" / "func" / "report.html",
        )

        extract._process_run(rp, as_pickle=True)

        assert rp.out_eye_path.parent.is_dir()
        assert calls[0][0] is rp
        assert calls[0][1]["as_pickle"] is True


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
        # Parallelism defaults to serial.
        assert captured["n_jobs"] == 1
        assert captured["threads_per_job"] is None

    def test_parallel_flags(self, monkeypatch, tmp_path: Path):
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
                "--n-jobs",
                "4",
                "--threads-per-job",
                "2",
            ],
        )

        extract.cli_main()
        assert captured["n_jobs"] == 4
        assert captured["threads_per_job"] == 2

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


# ---------------------------------------------------------------------------
# config-file support
# ---------------------------------------------------------------------------
class TestConfig:
    def test_load_config_reads_extract_section(self, tmp_path: Path):
        cfg = tmp_path / "run.yaml"
        cfg.write_text(
            "extract:\n"
            "  root: /data/bids\n"
            "  n_jobs: 4\n"
            "  filters:\n"
            "    task: [rest]\n"
            "slurm:\n"
            "  partition: defq\n"
        )
        loaded = extract._load_config(cfg)
        assert loaded["root"] == "/data/bids"
        assert loaded["n_jobs"] == 4
        assert loaded["filters"] == {"task": ["rest"]}
        assert "partition" not in loaded  # slurm section is ignored

    def test_load_config_missing_extract_section(self, tmp_path: Path):
        cfg = tmp_path / "run.yaml"
        cfg.write_text("slurm:\n  partition: defq\n")
        assert extract._load_config(cfg) == {}

    def test_convert_filter_value_sentinels(self):
        from bids.layout import Query

        assert extract._convert_filter_value("*") is Query.ANY
        assert extract._convert_filter_value("none") is Query.NONE
        assert extract._convert_filter_value("null") is Query.NONE
        assert extract._convert_filter_value(["rest", "*"]) == ["rest", Query.ANY]
        assert extract._convert_filter_value("rest") == "rest"

    def _write_config(self, tmp_path: Path, body: str) -> Path:
        cfg = tmp_path / "run.yaml"
        cfg.write_text(body)
        return cfg

    def test_config_seeds_arguments(self, monkeypatch, tmp_path: Path):
        cfg = self._write_config(
            tmp_path,
            "extract:\n"
            f"  root: {tmp_path}\n"
            "  derivatives_dir: fmriprep\n"
            "  n_jobs: 4\n"
            "  threads_per_job: 2\n"
            "  filters:\n"
            "    task: [rest]\n",
        )
        captured = {}
        monkeypatch.setattr(
            extract, "extract_eyeball_voxels", lambda **kw: captured.update(kw)
        )
        monkeypatch.setattr("sys.argv", ["mreyextract", "--config", str(cfg)])

        extract.cli_main()

        assert captured["root"] == str(tmp_path)
        assert captured["derivatives_dir"] == "fmriprep"
        assert captured["n_jobs"] == 4
        assert captured["threads_per_job"] == 2
        assert captured["filters"]["task"] == ["rest"]

    def test_cli_overrides_config(self, monkeypatch, tmp_path: Path):
        cfg = self._write_config(
            tmp_path,
            "extract:\n"
            f"  root: {tmp_path}\n"
            "  n_jobs: 4\n"
            "  filters:\n"
            "    task: [rest]\n",
        )
        captured = {}
        monkeypatch.setattr(
            extract, "extract_eyeball_voxels", lambda **kw: captured.update(kw)
        )
        monkeypatch.setattr(
            "sys.argv",
            ["mreyextract", "--config", str(cfg), "--n-jobs", "1", "--task", "rest2"],
        )

        extract.cli_main()

        # CLI value wins over the config value.
        assert captured["n_jobs"] == 1
        assert captured["filters"]["task"] == ["rest2"]

    def test_root_from_config_not_required_on_cli(self, monkeypatch, tmp_path: Path):
        cfg = self._write_config(tmp_path, f"extract:\n  root: {tmp_path}\n")
        captured = {}
        monkeypatch.setattr(
            extract, "extract_eyeball_voxels", lambda **kw: captured.update(kw)
        )
        monkeypatch.setattr("sys.argv", ["mreyextract", "--config", str(cfg)])

        # Should not raise even though --root is absent from the command line.
        extract.cli_main()
        assert captured["root"] == str(tmp_path)

    def test_unknown_config_key_errors(self, monkeypatch, tmp_path: Path):
        cfg = self._write_config(
            tmp_path, f"extract:\n  root: {tmp_path}\n  bogus_key: 1\n"
        )
        monkeypatch.setattr("sys.argv", ["mreyextract", "--config", str(cfg)])
        with pytest.raises(SystemExit):
            extract.cli_main()
