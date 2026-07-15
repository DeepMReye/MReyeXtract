"""Tests for :mod:`mreyextract.cli`."""

from pathlib import Path

import pytest

from mreyextract import cli


# ---------------------------------------------------------------------------
# cli_main
# ---------------------------------------------------------------------------
class TestCliMain:
    def test_parses_args_and_dispatches(self, monkeypatch, tmp_path: Path):
        captured = {}

        def _fake_extract(**kwargs):
            captured.update(kwargs)

        monkeypatch.setattr(cli, "extract_eyeball_voxels", _fake_extract)
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

        cli.cli_main()

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
            cli, "extract_eyeball_voxels", lambda **kw: captured.update(kw)
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

        cli.cli_main()
        assert captured["n_jobs"] == 4
        assert captured["threads_per_job"] == 2

    def test_bids_filter_file_merged(self, monkeypatch, tmp_path: Path):
        captured = {}
        monkeypatch.setattr(
            cli, "extract_eyeball_voxels", lambda **kw: captured.update(kw)
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

        cli.cli_main()
        assert captured["filters"]["session"] == "01"

    def test_entity_value_conversions(self, monkeypatch, tmp_path: Path):
        from bids.layout import Query

        captured = {}
        monkeypatch.setattr(
            cli, "extract_eyeball_voxels", lambda **kw: captured.update(kw)
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

        cli.cli_main()

        filters = captured["filters"]
        assert filters["subject"] == ["01"]
        assert filters["session"] == [Query.NONE]
        assert filters["task"] == [Query.ANY]
        assert filters["run"] == [3]

    def test_root_is_required(self, monkeypatch):
        monkeypatch.setattr("sys.argv", ["mreyextract"])
        with pytest.raises(SystemExit):
            cli.cli_main()


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
        loaded = cli._load_config(cfg)
        assert loaded["root"] == "/data/bids"
        assert loaded["n_jobs"] == 4
        assert loaded["filters"] == {"task": ["rest"]}
        assert "partition" not in loaded  # slurm section is ignored

    def test_load_config_missing_extract_section(self, tmp_path: Path):
        cfg = tmp_path / "run.yaml"
        cfg.write_text("slurm:\n  partition: defq\n")
        assert cli._load_config(cfg) == {}

    def test_convert_filter_value_sentinels(self):
        from bids.layout import Query

        assert cli._convert_filter_value("*") is Query.ANY
        assert cli._convert_filter_value("none") is Query.NONE
        assert cli._convert_filter_value("null") is Query.NONE
        assert cli._convert_filter_value(["rest", "*"]) == ["rest", Query.ANY]
        assert cli._convert_filter_value("rest") == "rest"

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
            cli, "extract_eyeball_voxels", lambda **kw: captured.update(kw)
        )
        monkeypatch.setattr("sys.argv", ["mreyextract", "--config", str(cfg)])

        cli.cli_main()

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
            cli, "extract_eyeball_voxels", lambda **kw: captured.update(kw)
        )
        monkeypatch.setattr(
            "sys.argv",
            ["mreyextract", "--config", str(cfg), "--n-jobs", "1", "--task", "rest2"],
        )

        cli.cli_main()

        # CLI value wins over the config value.
        assert captured["n_jobs"] == 1
        assert captured["filters"]["task"] == ["rest2"]

    def test_root_from_config_not_required_on_cli(self, monkeypatch, tmp_path: Path):
        cfg = self._write_config(tmp_path, f"extract:\n  root: {tmp_path}\n")
        captured = {}
        monkeypatch.setattr(
            cli, "extract_eyeball_voxels", lambda **kw: captured.update(kw)
        )
        monkeypatch.setattr("sys.argv", ["mreyextract", "--config", str(cfg)])

        # Should not raise even though --root is absent from the command line.
        cli.cli_main()
        assert captured["root"] == str(tmp_path)

    def test_unknown_config_key_errors(self, monkeypatch, tmp_path: Path):
        cfg = self._write_config(
            tmp_path, f"extract:\n  root: {tmp_path}\n  bogus_key: 1\n"
        )
        monkeypatch.setattr("sys.argv", ["mreyextract", "--config", str(cfg)])
        with pytest.raises(SystemExit):
            cli.cli_main()
