"""
MReyeCtract CLI
"""

import argparse
import json
import logging
from pathlib import Path

from bids.layout import Query

from mreyextract import enable_logging
from mreyextract.extract import extract_eyeball_voxels
from mreyextract.io import ENTITIES

logger = logging.getLogger(__name__)


def _load_config(path: Path) -> dict:
    """
    Load the ``extract`` section of a YAML run-config file.

    Parameters
    ----------
    path : Path
        Path to a YAML file with a top-level ``extract:`` mapping whose keys
        mirror the CLI options (using underscores, e.g. ``n_jobs``). A nested
        ``filters:`` mapping supplies BIDS entity filters.

    Returns
    -------
    dict
        The ``extract`` mapping, or an empty dict if the section is absent.
    """
    import yaml  # pylint: disable=import-outside-toplevel

    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return data.get("extract", {}) or {}


def _convert_filter_value(value):
    """
    Apply PyBIDS sentinel conversion to a config-supplied filter value.

    Parameters
    ----------
    value : object
        A scalar or list from the config's ``filters`` mapping. ``"*"`` becomes
        ``Query.ANY`` and ``"none"``/``"null"`` become ``Query.NONE``; lists are
        converted element-wise.

    Returns
    -------
    object
        The converted value.
    """

    def _conv(item):
        if item == "*":
            return Query.ANY
        if isinstance(item, str) and item.lower() in ("none", "null"):
            return Query.NONE
        return item

    if isinstance(value, list):
        return [_conv(item) for item in value]
    return _conv(value)


def cli_main() -> None:
    """
    Command-line entry point for the ``mreyextract`` console script.

    Parses arguments, optionally seeding defaults from a ``--config`` YAML file
    (explicit CLI flags take precedence), assembles BIDS entity filters
    (optionally merged from a ``--bids-filter-file``), configures logging and
    dispatches to :func:`extract_eyeball_voxels`.

    Returns
    -------
    None
    """

    def _pybids_none_any(dct):
        """
        Map filter-file sentinels to PyBIDS query constants.

        Parameters
        ----------
        dct : dict
            Entity filters loaded from JSON. ``None`` values become
            ``Query.NONE`` and ``"*"`` values become ``Query.ANY``.

        Returns
        -------
        dict
            The filters with sentinels replaced by PyBIDS query constants.
        """
        return {
            k: Query.NONE if v is None else (Query.ANY if v == "*" else v)
            for k, v in dct.items()
        }

    def entity_value(typ: type, prefix: str | None = None):
        """
        Build an argparse ``type`` converter for a BIDS entity value.

        Parameters
        ----------
        typ : type
            Callable applied to the final string (e.g. ``str`` or ``int``).
        prefix : str | None, optional
            Entity prefix (e.g. ``"sub"``) stripped from values like
            ``"sub-01"`` before conversion. Default ``None``.

        Returns
        -------
        Callable[[str], object]
            A converter mapping ``"*"`` to ``Query.ANY``, ``"none"``/``"null"``
            to ``Query.NONE`` and everything else through ``typ``.
        """

        def _conv(s: str):
            if s == "*":
                return Query.ANY
            if s.lower() in ("none", "null"):
                return Query.NONE
            if prefix:
                s = s.removeprefix(f"{prefix}-")
            return typ(s)

        return _conv

    def run_default(args, filters):
        """
        Dispatch parsed arguments to :func:`extract_eyeball_voxels`.

        Parameters
        ----------
        args : argparse.Namespace
            Parsed command-line arguments.
        filters : dict
            Assembled BIDS entity filters.
        """
        return extract_eyeball_voxels(
            root=args.root,
            derivatives_dir=args.derivatives_dir,
            filters=filters,
            bids_compatible=args.bids_compatible,
            force=args.force,
            as_pickle=args.as_pickle,
            glob_pattern=args.glob_pattern,
            n_jobs=args.n_jobs,
            threads_per_job=args.threads_per_job,
        )

    # First pass: discover a --config file so its values can seed defaults.
    config_parser = argparse.ArgumentParser(add_help=False)
    config_parser.add_argument("--config", type=Path)
    config_args, _ = config_parser.parse_known_args()

    config = _load_config(config_args.config) if config_args.config else {}
    config_filters = config.pop("filters", {}) or {}

    parser = argparse.ArgumentParser(
        prog="mreyextract", description="Run eye voxel extraction."
    )

    parser.add_argument(
        "--config",
        type=Path,
        required=False,
        help="YAML config file whose 'extract' section seeds the options below. "
        "Explicit CLI flags override values from the file.",
    )

    parser.add_argument(
        "--root",
        type=str,
        required="root" not in config,
        help="[BIDS] Root directory to look for BOLD files in.",
    )

    parser.add_argument(
        "--bids-compatible",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Whether root is BIDS compatible or not. Default is True.",
    )

    parser.add_argument(
        "--derivatives-dir",
        type=str,
        required=False,
        help="If --bids is True, specify the relative derivative directory "
        "you want to extract from. E.g., fmriprep",
    )

    parser.add_argument(
        "--force",
        action="store_true",
        required=False,
        help="Overwrite existing derivatives if they exist",
    )

    parser.add_argument(
        "--as-pickle",
        action="store_true",
        required=False,
        help="Saves the eye voxels as pickle files instead of Nifti",
    )

    parser.add_argument(
        "--n-jobs",
        type=int,
        default=1,
        required=False,
        help="Number of runs to process in parallel (loky process pool). "
        "1 (default) runs serially; -1 uses all available cores.",
    )

    parser.add_argument(
        "--threads-per-job",
        type=int,
        default=None,
        required=False,
        help="ITK/ANTs threads per parallel job. Defaults to "
        "cores // n_jobs to avoid oversubscribing the machine.",
    )

    parser.add_argument(
        "--log-level",
        default="INFO",
        required=False,
        help="Logging level (DEBUG, INFO, WARNING, ERROR).",
    )

    parser.add_argument(
        "--glob-pattern",
        default="sub-*/**/func/*_bold.nii*",
        required=False,
        help="If non-bids, specify the regexp to glob through the root directory. "
        "Default is 'sub-*/**/func/*_bold.nii*'",
    )

    for name, (typ, prefix) in ENTITIES.items():
        parser.add_argument(
            f"--{name}",
            nargs="+",
            type=entity_value(typ, prefix),
            help=f"Optional {name} filter for file querying. "
            f"For safety, wrap everything in quote marks. E.g., '*'",
        )

    parser.add_argument(
        "--bids-filter-file",
        type=Path,
        required=False,
        help="JSON of BIDS entity filters",
    )

    # Seed argparse defaults from the config so CLI flags still override them.
    if config:
        # pylint: disable-next=protected-access
        valid_dests = {action.dest for action in parser._actions}
        unknown = set(config) - valid_dests
        if unknown:
            parser.error(f"Unknown key(s) under 'extract' in config: {sorted(unknown)}")
        parser.set_defaults(**{key: config[key] for key in config})

    args = parser.parse_args()

    # Paths coming from the config arrive as plain strings.
    if isinstance(args.bids_filter_file, str):
        args.bids_filter_file = Path(args.bids_filter_file)

    # Filters: config first, then CLI entity flags override, then filter file.
    filters = {k: _convert_filter_value(v) for k, v in config_filters.items()}
    filters.update(
        {k: v for k, v in vars(args).items() if k in ENTITIES and v is not None}
    )

    if args.bids_filter_file:
        filters.update(
            json.loads(
                args.bids_filter_file.read_text(encoding="utf-8"),
                object_hook=_pybids_none_any,
            )
        )

    enable_logging(level=args.log_level.upper())

    logger.info("Starting eye-voxel extraction.")

    logger.info("Filtering files on %s", json.dumps(filters, default=str))

    run_default(args, filters)
