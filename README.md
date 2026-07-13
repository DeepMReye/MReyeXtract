[![License: GPL v3](https://img.shields.io/badge/License-GPL%20v3-blue.svg)](http://www.gnu.org/licenses/gpl-3.0)
![py311 status](https://img.shields.io/badge/python3.11-supported-green.svg)
[![NatNeuro Paper](https://img.shields.io/badge/DOI-10.1038%2Fs41593--021--00947--w-blue)](https://doi.org/10.1038/s41593-021-00947-w)
[![DeepMReye](https://img.shields.io/badge/built%20on-DeepMReye-orange.svg)](https://github.com/DeepMReye/DeepMReye)

# MReyeXtract: eye-voxel extraction for fMRI

MReyeXtract extracts the eyeballs from 4D BOLD images so they can be fed to
[DeepMReye](https://github.com/DeepMReye/DeepMReye) or other gaze-decoding
models. Each run is registered to a DeepMReye eye template with
[ANTsPy](https://github.com/ANTsX/ANTsPy), cropped to the eye masks, and saved
alongside an interactive HTML quality-control report. It runs on
[BIDS](https://bids.neuroimaging.io/) datasets out of the box, and on arbitrary
directory trees via a glob pattern.

If you have questions or comments, please reach out (see [Correspondence](#correspondence)).

## Installation

MReyeXtract requires <u>**Python 3.11**</u>.

### Option 1: Pip install

#### Pip installation

```bash
python3.11 -m venv .venv
source .venv/bin/activate
pip install -e .
```

For development (tests, linting, type checking):

```bash
pip install -e ".[dev]" pytest pytest-cov pytest-mock
```

#### Anaconda / Miniconda installation

```bash
conda create --name mreyextract python=3.11
conda activate mreyextract
pip install -e .
```

If ANTsPy does not resolve a wheel for your platform, install it manually first
(see the [ANTsPy installation guide](https://github.com/ANTsX/ANTsPy)) and then
re-run the install above.

## Usage

Installing the package exposes the `mreyextract` command-line tool. Run
`mreyextract --help` for the full list of options.

### BIDS datasets (default)

```bash
mreyextract --root /path/to/bids_dataset
```

To extract from a derivatives pipeline (e.g. fMRIPrep outputs):

```bash
mreyextract --root /path/to/bids_dataset --derivatives-dir fmriprep
```

Restrict which BOLD files are processed with BIDS entities. Each accepts one or
more values; `'*'` matches any value and `'none'`/`'null'` matches files where
the entity is absent:

```bash
mreyextract --root /path/to/bids_dataset \
    --subject 01 02 --task rest --run '*'
```

Filters can also be supplied as a JSON file via `--bids-filter-file`.

### Non-BIDS directories

Point `--no-bids-compatible` at any tree and provide a glob pattern:

```bash
mreyextract --root /path/to/data --no-bids-compatible \
    --glob-pattern 'sub-*/**/func/*_bold.nii*'
```

### Options

| Option | Description |
| --- | --- |
| `--root` | Root directory to search for BOLD files (required). |
| `--bids-compatible` / `--no-bids-compatible` | Treat `--root` as a BIDS dataset. Default: BIDS. |
| `--derivatives-dir` | Relative derivatives directory to extract from (e.g. `fmriprep`). |
| `--glob-pattern` | Glob for non-BIDS mode. Default: `sub-*/**/func/*_bold.nii*`. |
| `--force` | Overwrite existing outputs instead of skipping them. |
| `--as-pickle` | Save the masked eye voxels as a pickled array instead of NIfTI. |
| `--log-level` | Logging verbosity: `DEBUG`, `INFO`, `WARNING`, `ERROR`. Default: `INFO`. |
| `--bids-filter-file` | Path to a JSON file of BIDS entity filters. |

### Python API

The extraction entry point can also be called directly:

```python
from mreyextract.extract import extract_eyeball_voxels

extract_eyeball_voxels(
    root="/path/to/bids_dataset",
    glob_pattern="sub-*/**/func/*_bold.nii*",
    bids_compatible=True,
    filters={"task": "rest"},
)
```

## Data formats

Inputs are 4D <u>**BOLD**</u> images in NIfTI format (`.nii` / `.nii.gz`).
Outputs are written to a BIDS-style derivatives folder under the dataset root:

```
<root>/derivatives/mreyextract/
    dataset_description.json
    sub-01/func/
        sub-01_task-rest_run-1_desc-eye_bold.nii.gz   # masked eye voxels
        sub-01_task-rest_run-1_desc-eye_report.html   # QC report
```

With `--as-pickle`, the eye voxels are saved as a pickled NumPy array
(`*_desc-eye_timeseries.p`) instead of NIfTI. Existing outputs are skipped
unless `--force` is passed.

## Hardware requirements

Registration is CPU-based and runs per BOLD run. A standard workstation is
sufficient; no GPU is required. Memory scales with image size — 4D BOLD runs are
held in memory during registration, so allow several GB of free RAM for
high-resolution or long acquisitions.

## Software requirements

MReyeXtract is developed and tested on Python 3.11. Core dependencies (installed
automatically):

```
numpy      (<2.0.0)
nibabel    (>=5.3.2)
antspyx    (>=0.6.1)
scipy      (>=1.15.1)
plotly     (>=6.5.0)
pybids     (>=0.22.0)
```

## Tests

```bash
pytest
```

## BIDS app

MReyeXtract reads and writes BIDS-compatible layouts: it queries BOLD files with
[PyBIDS](https://github.com/bids-standard/pybids), honours BIDS entity filters,
and emits a `derivatives/mreyextract/` folder with a `dataset_description.json`.

## Correspondence

If you have questions, comments or inquiries, please reach out to us:
zachnudels[at]gmail.com
