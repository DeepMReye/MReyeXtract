"""
Preprocessing pipeline to clean and extract eye voxels from fmri data
"""

import os
import re
from functools import lru_cache
from pathlib import Path

import logging

from joblib import Parallel, delayed
from joblib.externals.loky import cpu_count as loky_cpu_count

from bids import BIDSLayout, BIDSLayoutIndexer

from mreyextract import preprocess, _ensure_worker_logging
from mreyextract.io import mreyextract_root, RunPaths, PATTERN, DESC_ADD

logger = logging.getLogger(__name__)


def strip_nifti_ext(name: str) -> str:
    """
    Remove the NIfTI extension from a filename.

    Parameters
    ----------
    name : str
        Filename ending in ``.nii`` or ``.nii.gz``.

    Returns
    -------
    str
        ``name`` with the trailing ``.nii``/``.nii.gz`` extension removed.

    Raises
    ------
    ValueError
        If ``name`` does not end in a recognised NIfTI extension.
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
    Build the input/output paths for a plain (non-BIDS) directory tree.

    Parameters
    ----------
    root : Path | str
        Directory to search for BOLD files.
    glob_pattern : str
        Glob, relative to ``root``, selecting candidate BOLD files
        (e.g. ``"sub-*/**/func/*_bold.nii*"``).
    output_dir : Path
        Derivatives directory that outputs are written under. Files already
        inside it are skipped so its own outputs are never re-ingested.
    as_pickle : bool, optional
        If ``True`` the eye output uses a ``.p`` (pickle) extension instead of
        ``.nii.gz``. Default ``False``.
    force : bool, optional
        If ``True`` include runs whose output already exists; otherwise they are
        skipped. Default ``False``.

    Returns
    -------
    list[RunPaths]
        One :class:`~mreyextract.io.RunPaths` per BOLD file to process, mirroring
        the input layout under ``output_dir``.

    Raises
    ------
    ValueError
        If two different inputs map to the same eye-output path.
    """
    ext = ".p" if as_pickle else ".nii.gz"

    run_paths = []
    seen: dict[Path, Path] = {}
    for in_file in sorted(Path(root).glob(glob_pattern)):
        in_file = in_file.resolve()
        if not in_file.name.endswith((".nii", ".nii.gz")):
            continue
        if output_dir in in_file.parents:  # don't re-ingest our own output
            continue

        stem = strip_nifti_ext(in_file.name)
        rel = in_file.relative_to(root).parent
        out_eye = output_dir / rel / f"{stem}_{DESC_ADD}{ext}"
        out_report = output_dir / rel / f"{stem}_{DESC_ADD}_report.html"

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
    Build a :class:`~bids.BIDSLayout` for the given dataset.

    Parameters
    ----------
    root : str | Path
        BIDS dataset root.
    derivatives_dir : str | Path | None
        Relative derivatives pipeline to index under ``root/derivatives``
        (e.g. ``"fmriprep"``). When ``None`` the raw dataset at ``root`` is
        indexed instead.

    Returns
    -------
    BIDSLayout
        A validation-free layout indexed without metadata for speed.

    Raises
    ------
    FileNotFoundError
        If the resolved target directory does not exist.
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
    Build the input/output paths for a BIDS dataset.

    Parameters
    ----------
    root : str | Path
        BIDS dataset root.
    derivatives_dir : str | Path | None
        Relative derivatives pipeline to extract from (e.g. ``"fmriprep"``), or
        ``None`` to use the raw dataset.
    output_dir : Path
        Derivatives directory that outputs are written under.
    filters : dict[str, str] | None, optional
        Extra BIDS entity filters passed to ``layout.get`` (e.g.
        ``{"task": "rest"}``). Default ``None`` (no additional filtering).
    force : bool, optional
        If ``True`` include runs whose output already exists; otherwise they are
        skipped. Default ``False``.
    as_pickle : bool, optional
        If ``True`` the eye output uses the ``timeseries``/``.p`` (pickle)
        naming instead of ``bold``/``.nii.gz``. Default ``False``.

    Returns
    -------
    list[RunPaths]
        One :class:`~mreyextract.io.RunPaths` per matching BOLD file.

    Raises
    ------
    ValueError
        If two different inputs map to the same eye-output path.
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

        # Append (not overwrite) the eye marker to the input's desc so eye
        # outputs from, e.g., raw and preprocessed BOLD stay distinct:
        # desc-preproc -> desc-preproc_eye, and no desc -> desc-eye.
        orig_desc = ents.get("desc")
        eye_desc = f"{orig_desc}_{DESC_ADD}" if orig_desc else DESC_ADD

        ents.update(desc=eye_desc, suffix=suffix, extension=ext)
        out_eye = output_dir / layout.build_path(
            ents, path_patterns=[PATTERN], validate=False, absolute_paths=False
        )

        # With every entity preserved in PATTERN this should not fire for a valid
        # dataset; kept as a cheap backstop against silently overwriting outputs.
        if out_eye in seen:
            raise ValueError(f"Collision: {seen[out_eye]} and {file.path} -> {out_eye}")
        seen[out_eye] = file.path

        if out_eye.exists() and not force:
            logger.info("Skipping %s that already exists", out_eye)
            continue

        ents.update(suffix="report", extension="html")
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


@lru_cache(maxsize=1)
def _cached_masks():
    """
    Load masks/template once per process.

    Wrapped in ``lru_cache`` so that, under a loky worker pool, each worker
    reads the (small) mask NIfTIs from disk exactly once and reuses them across
    every run it processes. Cleared at the start of each top-level extraction
    so a fresh call always reloads.
    """
    return preprocess.get_masks()


def _process_run(run_path: RunPaths, as_pickle: bool) -> None:
    """
    Extract eye voxels for a single run.

    Self-contained so it can execute in a loky worker process: it reconfigures
    logging, lazily loads the (worker-local, cached) masks, ensures the output
    directory exists, and runs the extraction. The runs are independent — each
    reads its own input and writes to a distinct output path — so this is safe
    to call concurrently.

    Parameters
    ----------
    run_path : RunPaths
        Input and output paths for the single run to process.
    as_pickle : bool
        If ``True`` the eye voxels are written as a pickled NumPy array;
        otherwise they are written as NIfTI.
    """
    _ensure_worker_logging()
    eyemask_small, eyemask_big, dme_template, _, x_edges, y_edges, z_edges = (
        _cached_masks()
    )

    logger.info("Processing file %s", run_path.in_path)
    run_path.out_eye_path.parent.mkdir(parents=True, exist_ok=True)

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


def extract_eyeball_voxels(  # pylint: disable=too-many-locals
    root: str | Path,
    glob_pattern: str,
    bids_compatible: bool = True,
    derivatives_dir: str | None = None,
    filters: dict[str, str] | None = None,
    force: bool = False,
    as_pickle: bool = False,
    n_jobs: int = 1,
    threads_per_job: int | None = None,
) -> None:
    """
    Extract eye voxels from cleaned fmri images.

    Parameters
    ----------
    root : str | Path
        Directory to search for BOLD files.
    glob_pattern : str
        Glob used to find BOLD files when ``bids_compatible`` is ``False``.
        Ignored in BIDS mode.
    bids_compatible : bool, optional
        If ``True`` (default) ``root`` is treated as a BIDS dataset and queried
        with PyBIDS; otherwise ``glob_pattern`` is used.
    derivatives_dir : str | None, optional
        In BIDS mode, the relative derivatives pipeline to extract from
        (e.g. ``"fmriprep"``). Default ``None`` (raw dataset).
    filters : dict[str, str] | None, optional
        BIDS entity filters applied in BIDS mode (e.g. ``{"task": "rest"}``).
        Default ``None``.
    force : bool, optional
        If ``True`` reprocess runs whose output already exists. Default
        ``False``.
    as_pickle : bool, optional
        If ``True`` save eye voxels as pickled NumPy arrays instead of NIfTI.
        Default ``False``.
    n_jobs : int, optional
        Number of runs to process in parallel using a loky (process) pool.
        ``1`` (default) runs serially; ``-1`` uses all available cores.
    threads_per_job : int | None, optional
        ITK/ANTs threads each job may use. When ``None`` it is chosen so that
        ``n_jobs * threads_per_job`` is roughly the CPU count, avoiding
        oversubscription (ANTs registration is itself multithreaded).

    Returns
    -------
    None
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

    # Masks are loaded lazily inside each worker (see _cached_masks); drop any
    # cache from a previous call so a fresh extraction reloads.
    _cached_masks.cache_clear()

    # Split cores between across-run parallelism and each run's own ANTs/ITK
    # threading so we don't oversubscribe the machine. loky's cpu_count honours
    # CPU affinity and cgroup quotas, so this respects a SLURM/container
    # allocation instead of seeing the whole node like os.cpu_count() would.
    n_cpus = loky_cpu_count() or 1
    effective_jobs = n_cpus if n_jobs in (-1, 0) else n_jobs
    if threads_per_job is None:
        threads_per_job = max(1, n_cpus // max(1, effective_jobs))
    # Inherited by loky workers spawned below; also caps the serial path.
    os.environ["ITK_GLOBAL_DEFAULT_NUMBER_OF_THREADS"] = str(threads_per_job)

    logger.info(
        "Processing %d run(s) with n_jobs=%d and %d ITK thread(s) per job",
        len(run_paths),
        n_jobs,
        threads_per_job,
    )

    if n_jobs == 1:
        for run_path in run_paths:
            _process_run(run_path, as_pickle=as_pickle)
    else:
        Parallel(n_jobs=n_jobs, backend="loky")(
            delayed(_process_run)(run_path, as_pickle=as_pickle)
            for run_path in run_paths
        )
