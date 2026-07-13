"""
IO methods for package
"""

import json
from dataclasses import dataclass
from pathlib import Path


@dataclass
class RunPaths:
    """
    Input and output paths for eyeball extraction
    """

    in_path: Path
    out_eye_path: Path
    out_report_path: Path


def _write_bids_description(path: Path):
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
    Construct the derivatives root for MReyeXtract
    Parameters
    ----------
    root

    Returns
    -------

    """
    root = Path(root)
    if not root.exists():
        raise FileNotFoundError(f"Could not find data directory {root}")

    deriv_root = root / "derivatives" / "mreyextract"
    deriv_root.mkdir(parents=True, exist_ok=True)
    _write_bids_description(deriv_root)
    return deriv_root
