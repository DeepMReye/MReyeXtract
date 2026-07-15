"""
IO methods for package
"""

import json
from dataclasses import dataclass
from pathlib import Path

# ---------------------------------------- #
# BIDS CONSTANTS
# ---------------------------------------- #

# Every optional entity is preserved so the eye-output name is never less
# specific than its input (which would silently map two inputs onto one file).
# Placeholders use PyBIDS entity names; entities appear in canonical BIDS order.
PATTERN = (
    "sub-{subject}[/ses-{session}]/{datatype}/"
    "sub-{subject}[_ses-{session}][_task-{task}][_acq-{acquisition}]"
    "[_ce-{ceagent}][_rec-{reconstruction}][_dir-{direction}][_run-{run}]"
    "[_mod-{modality}][_echo-{echo}][_flip-{flip}][_inv-{inv}][_mt-{mt}]"
    "[_part-{part}][_proc-{proc}][_hemi-{hemi}][_space-{space}]"
    "[_res-{res}][_den-{den}][_label-{label}][_desc-{desc}]"
    "_{suffix}{extension}"
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

DESC_ADD = "eye"


@dataclass
class RunPaths:
    """
    Input and output paths for eyeball extraction.

    Parameters
    ----------
    in_path : Path
        Path to the input BOLD image to process.
    out_eye_path : Path
        Path the extracted eye voxels are written to (NIfTI or pickle).
    out_report_path : Path
        Path the HTML quality-control report is written to.
    """

    in_path: Path
    out_eye_path: Path
    out_report_path: Path


def _write_bids_description(path: Path):
    """
    Write a minimal ``dataset_description.json`` into a derivatives directory.

    Parameters
    ----------
    path : Path
        Derivatives directory to write into. If a description already exists it
        is left untouched.
    """
    try:
        from ._version import __version__  # pylint: disable=import-outside-toplevel
    except ImportError:
        __version__ = "0.0.0+unknown"

    description_path = path / "dataset_description.json"
    if description_path.exists():
        return

    description = {
        "Name": "MReyeXtract Outputs",
        "BIDSVersion": "1.8.0",
        "PipelineDescription": {"Name": "MReyeXtract", "Version": __version__},
    }
    json.dump(description, description_path.open("w"), indent=4)


def mreyextract_root(root: Path | str) -> Path:
    """
    Construct (and create) the derivatives root for MReyeXtract.

    Parameters
    ----------
    root : Path | str
        Existing dataset root. The derivatives tree is created beneath it.

    Returns
    -------
    Path
        The ``<root>/derivatives/mreyextract`` directory, created if needed and
        seeded with a ``dataset_description.json``.

    Raises
    ------
    FileNotFoundError
        If ``root`` does not exist.
    """
    root = Path(root)
    if not root.exists():
        raise FileNotFoundError(f"Could not find data directory {root}")

    deriv_root = root / "derivatives" / "mreyextract"
    deriv_root.mkdir(parents=True, exist_ok=True)
    _write_bids_description(deriv_root)
    return deriv_root
