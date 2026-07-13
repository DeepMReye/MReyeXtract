"""
Preprocessing pipeline to clean and extract eye voxels from fmri data
"""

import json
import re
from pathlib import Path

import argparse
import logging

from bids.layout import Query
from bids import BIDSLayout, BIDSLayoutIndexer

from mreyextract import preprocess, enable_logging
from mreyextract.io import mreyextract_root, RunPaths

logger = logging.getLogger(__name__)

PATTERN = (
    "sub-{subject}[/ses-{session}]/{datatype}/"
    "sub-{subject}[_ses-{session}][_task-{task}][_run-{run}]"
    "[_space-{space}][_desc-{desc}]_{suffix}{extension}"
)

ENTITIES = {
    "subject": (str, "sub"),
    "session": (str, "ses"),
    "task": (str, None),
    "run": (int, None),
    "space": (str, None),
    "desc": (str, None),
    "echo": (int, None),
}


def strip_nifti_ext(name: str) -> str:
    """
    Remove nifti extension from filename
    Parameters
    ----------
    name : str

    Returns
    -------

    """
    for ext in (".nii.gz", ".nii"):
        if name.endswith(ext):
            return name[: -len(ext)]
    raise ValueError(f"Not a NIfTI filename: {name}")


def non_bids_paths(
    root: Path | str,
    glob_pattern: str,
    output_dir: Path,
    as_pickle: bool = False,
    force: bool = False,
):
    """

    Parameters
    ----------
    root : Path
    glob_pattern : str
    output_dir : Path,
    as_pickle : bool
    force : bool = False

    Returns
    -------

    """
    ext = ".p" if as_pickle else ".nii.gz"

    run_paths = []
    seen: dict[Path, Path] = {}
    for in_file in sorted(Path(root).glob(glob_pattern)):
        in_file = in_file.resolve()
        if not in_file.name.endswith((".nii", ".nii.gz")):  # *.nii* also hits .nii.json
            continue
        if output_dir in in_file.parents:  # don't re-ingest our own output
            continue

        stem = strip_nifti_ext(in_file.name)
        rel = in_file.relative_to(root).parent
        out_eye = output_dir / rel / f"{stem}_desc-eye{ext}"
        out_report = output_dir / rel / f"{stem}_desc-eye_report.html"

        if out_eye in seen:
            raise ValueError(f"Collision: {seen[out_eye]} and {in_file} -> {out_eye}")
        seen[out_eye] = in_file

        if out_eye.exists() and not force:
            logger.info("Skipping %s that already exists", out_eye)
            continue

        run_paths.append(
            RunPaths(
                in_path=in_file,
                out_eye_path=out_eye,
                out_report_path=out_report,
            )
        )

        logger.debug(
            "Adding in file %s and outfile %s and report %s",
            in_file,
            out_eye,
            out_report,
        )

    return run_paths


def make_layout(
    root: str | Path,
    derivatives_dir: str | Path | None,
) -> BIDSLayout:
    """
    Make a BIDSLayout for the given args

    Parameters
    ----------
    root: str | Path
    derivatives_dir: str | Path | None

    Returns
    -------

    """
    if derivatives_dir is None:
        target = Path(root)
        config = None
    else:
        target = Path(root) / "derivatives" / derivatives_dir
        config = ["bids", "derivatives"]

    if not target.is_dir():
        raise FileNotFoundError(f"No BIDS target directory: {target}")

    indexer = BIDSLayoutIndexer(
        validate=False,
        index_metadata=False,  # biggest win; you never call get_metadata()
        ignore=[re.compile(r"^\."), "figures", "log", "sourcedata"],
    )
    return BIDSLayout(str(target), validate=False, config=config, indexer=indexer)


def bids_paths(  # pylint: disable=too-many-locals
    root: str | Path,
    derivatives_dir: str | Path | None,
    output_dir: Path,
    filters: dict[str, str] | None = None,
    force: bool = False,
    as_pickle: bool = False,
) -> list[RunPaths]:
    """

    Parameters
    ----------
    root : str | Path
    derivatives_dir : str | Path | None
    output_dir : Path
    filters : dict[str, str] | None
    force: bool
    as_pickle : bool

    Returns
    -------
    list[RunPaths]

    """

    logger.info("Reading BIDS Layout")

    layout: BIDSLayout = make_layout(root=str(root), derivatives_dir=derivatives_dir)

    if filters is None:
        filters = {}

    logger.info("Reading BOLD files")

    files = layout.get(
        suffix="bold",
        extension=[".nii", ".nii.gz"],
        **filters,
    )

    run_paths = []
    seen: dict[Path, Path] = {}

    for file in files:
        ents = file.get_entities()
        if as_pickle:
            suffix = "timeseries"
            ext = ".p"
        else:
            suffix = "bold"
            ext = ".nii.gz"

        ents.update(desc="eye", suffix=suffix, extension=ext)
        out_eye = output_dir / layout.build_path(
            ents, path_patterns=[PATTERN], validate=False, absolute_paths=False
        )

        if out_eye in seen:
            raise ValueError(f"Collision: {seen[out_eye]} and {file.path} -> {out_eye}")
        seen[out_eye] = file.path

        if out_eye.exists() and not force:
            logger.info("Skipping %s that already exists", out_eye)
            continue

        ents.update(desc="eye", suffix="report", extension="html")
        out_report = output_dir / layout.build_path(
            ents, path_patterns=[PATTERN], validate=False, absolute_paths=False
        )

        run_paths.append(
            RunPaths(
                in_path=Path(file.path),
                out_eye_path=out_eye,
                out_report_path=out_report,
            )
        )

        logger.debug(
            "Adding in file %s and outfile %s and report %s",
            file.path,
            out_eye,
            out_report,
        )

    return run_paths


def extract_eyeball_voxels(  # pylint: disable=too-many-locals
    root: str | Path,
    glob_pattern: str,
    bids_compatible: bool = True,
    derivatives_dir: str | None = None,
    filters: dict[str, str] | None = None,
    force: bool = False,
    as_pickle: bool = False,
) -> None:
    """
    Extract eye voxels from cleaned fmri images.

    Parameters
    ----------
    root: str
    glob_pattern: str
    bids_compatible: bool
    derivatives_dir: str | None
    filters: dict[str, str] | None
    force: bool
    as_pickle: bool

    Returns
    -------

    """

    output_dir = mreyextract_root(root).resolve()
    root = Path(root).resolve()

    if bids_compatible:
        run_paths = bids_paths(
            root=root,
            derivatives_dir=derivatives_dir,
            as_pickle=as_pickle,
            output_dir=output_dir,
            force=force,
            filters=filters,
        )

    else:
        run_paths = non_bids_paths(
            root=root,
            as_pickle=as_pickle,
            glob_pattern=glob_pattern,
            output_dir=output_dir,
            force=force,
        )

    if len(run_paths) == 0:
        logger.warning(
            "Could not find any BOLD files in %s with specified options", root
        )
        return

    # Preload masks and template
    eyemask_small, eyemask_big, dme_template, _, x_edges, y_edges, z_edges = (
        preprocess.get_masks()
    )

    for run_path in run_paths:
        logger.info("Processing file %s", run_path.in_path)
        run_path.out_eye_path.parent.mkdir(parents=True, exist_ok=True)

        # It takes long to build up the layout so I need to cache it as a sqllite index
        preprocess.extract_mask(
            run_path,
            dme_template,
            eyemask_big,
            eyemask_small,
            x_edges,
            y_edges,
            z_edges,
            as_pickle=as_pickle,
        )


# -----------------------
# Main Functions
# -----------------------


def cli_main() -> None:
    """
    Main entry point
    Returns
    -------

    """

    def _pybids_none_any(dct):
        return {
            k: Query.NONE if v is None else (Query.ANY if v == "*" else v)
            for k, v in dct.items()
        }

    def entity_value(typ, prefix=None):
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
        return extract_eyeball_voxels(
            root=args.root,
            derivatives_dir=args.derivatives_dir,
            filters=filters,
            bids_compatible=args.bids_compatible,
            force=args.force,
            as_pickle=args.as_pickle,
            glob_pattern=args.glob_pattern,
        )

    parser = argparse.ArgumentParser(
        prog="mreyextract", description="Run eye voxel extraction."
    )

    parser.add_argument(
        "--root",
        type=str,
        required=True,
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

    args = parser.parse_args()
    filters = {k: v for k, v in vars(args).items() if k in ENTITIES and v is not None}

    if args.bids_filter_file:
        filters.update(
            json.loads(args.bids_filter_file.read_text(), object_hook=_pybids_none_any)
        )

    enable_logging(level=args.log_level.upper())

    logger.info("Starting eye-voxel extraction.")

    logger.info("Filtering files on %s", json.dumps(filters, default=str))

    run_default(args, filters)
