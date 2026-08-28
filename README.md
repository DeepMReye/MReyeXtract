[![License: GPL v3](https://img.shields.io/badge/License-GPL%20v3-blue.svg)](http://www.gnu.org/licenses/gpl-3.0)
[![PyPI](https://img.shields.io/pypi/v/mreyextract.svg)](https://pypi.org/project/mreyextract/)
![py311 status](https://img.shields.io/badge/python3.11-supported-green.svg)
[![NatNeuro Paper](https://img.shields.io/badge/DOI-10.1038%2Fs41593--021--00947--w-blue)](https://doi.org/10.1038/s41593-021-00947-w)
[![DeepMReye](https://img.shields.io/badge/built%20on-DeepMReye-orange.svg)](https://github.com/DeepMReye/DeepMReye)

# MReyeXtract: eye-voxel extraction for fMRI
<img src="media/brain.png" width="300" alt="Image of a brain with masks">

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

### From PyPI

Install the latest release from [PyPI](https://pypi.org/project/mreyextract/)
into a virtual environment:

```bash
python3.11 -m venv .venv
source .venv/bin/activate
pip install mreyextract
```

Or into a conda environment:

```bash
conda create --name mreyextract python=3.11
conda activate mreyextract
pip install mreyextract
```

If ANTsPy does not resolve a wheel for your platform, install it manually first
(see the [ANTsPy installation guide](https://github.com/ANTsX/ANTsPy)) and then
re-run the install above.

### From source

To modify or contribute to MReyeXtract, install an editable checkout with the
development extras — see [CONTRIBUTING.md](CONTRIBUTING.md).

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

Filters can also be supplied as a JSON file via `--bids-filter-file` (the
BIDS-App convention). Precedence, lowest to highest, is: YAML config (see later) →
JSON BIDS filter file → explicit CLI entity flags, so the command line always
wins.

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
| `--n-jobs` | Number of runs to process in parallel. `1` (default) is serial; `-1` uses all cores. |
| `--threads-per-job` | ITK/ANTs threads per parallel job. Default: `cores // n_jobs`. |
| `--log-level` | Logging verbosity: `DEBUG`, `INFO`, `WARNING`, `ERROR`. Default: `INFO`. |
| `--bids-filter-file` | Path to a JSON file of BIDS entity filters. |
| `--config` | Path to a YAML config file that seeds the options above. |

### Config file

Rather than passing many flags, the run can be described in a YAML file and
loaded with `--config`. Keys under `extract` mirror the CLI options (with
underscores); explicit flags on the command line override the file:

```yaml
# run.yaml
extract:
  root: /abs/path/to/bids_dataset
  derivatives_dir: fmriprep
  n_jobs: 4
  threads_per_job: 2
  filters:
    task: [rest]        # "*" -> any, "none"/"null" -> absent
```

```bash
mreyextract --config run.yaml            # everything from the file
mreyextract --config run.yaml --force    # override a single option
```

### Parallel processing

Runs are independent, so they can be processed in parallel across a
[loky](https://joblib.readthedocs.io/en/stable/parallel.html) process pool:

```bash
mreyextract --root /path/to/bids_dataset --n-jobs 8
```

Registration (ANTsPy/ITK) is itself multithreaded, so the tool splits the
available cores between across-run parallelism (`--n-jobs`) and each run's own
threads (`--threads-per-job`) to avoid oversubscription. By default
`threads-per-job` is set to `cores // n_jobs`, where `cores` respects the CPU
allocation (SLURM/cgroup affinity), not just the physical node — so the default
is safe when running interactively inside an allocation. Tune both together on a
shared server, and keep an eye on memory — each concurrent run holds a full 4D
BOLD volume in RAM.

### Reviewing the reports

Installing the package also exposes `mreyextract-view`, a small local web app for
paging through the QC reports and marking each one good or bad:

```bash
mreyextract-view --root /path/to/bids_dataset
```

It serves the reports under `<root>/derivatives/mreyextract` at
<http://127.0.0.1:8000> and opens a browser. The sidebar groups every report by
subject and colours it by verdict, and notes can be attached to any report.

**Reviewing a whole dataset is one keypress per report.** With **advance**
ticked (the default), `g` marks the report good and `b` marks it bad, and either
immediately moves on to the next one — so a dataset can be worked through
without touching the mouse: look at the report, press one key, look at the next.
`u` clears a verdict, and the up/down arrow keys move between reports without
rating one. The next report is loaded in the background while the current one is
on screen, so it is ready the moment you advance.

The counts in the header and the status light beside each report change **only
once the verdict is in `qc_ratings.tsv`**. A light stays dimmed while its write
is still in flight, so a solid colour and a rising count confirm the file on
disk was actually updated; a write that fails says so and leaves the report at
its previous verdict rather than a colour that was never saved.

Point it at reports written by another tool (e.g. DeepMReye's `report_*.html`)
with `--review-dir`:

```bash
mreyextract-view --review-dir /path/to/reports
```

| Option | Description |
| --- | --- |
| `--root` | Dataset root whose `derivatives/mreyextract` reports are reviewed. |
| `--review-dir` | Review this directory instead of a dataset's derivatives. |
| `--pattern` | Glob(s) selecting report files. Default: `**/*_report.html **/report_*.html`. |
| `--host` | Interface to bind. Default: `127.0.0.1`. |
| `--port` | Port to serve on. Default: `8000`; `0` picks a free port. |
| `--browser` / `--no-browser` | Open a browser on startup. Default: open. |
| `--log-level` | Logging verbosity. Default: `INFO`. |

Verdicts are written to `qc_ratings.tsv` in the reviewed directory — next to the
reports and eye voxels they describe — as they are made, so a review can be
interrupted and resumed, and two people can review the same dataset at once. The
file is a plain table, ready for the analysis that follows:

```python
import pandas as pd

ratings = pd.read_csv("derivatives/mreyextract/qc_ratings.tsv", sep="\t")
usable = ratings.loc[ratings["status"] == "good", "path"]
```

Reports on a remote machine can be reviewed over an SSH tunnel
(`ssh -L 8000:127.0.0.1:8000 user@host`) without copying anything down; the
viewer binds to localhost only, and everything it serves is read from that
directory.

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
    qc_ratings.tsv                                    # QC verdicts, if reviewed
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
joblib     (>=1.3)
pyyaml     (>=6.0)
```

## Running on a cluster (SLURM)

The [`slurm/`](slurm) directory contains a ready-to-adapt job-array template
(`submit.sbatch`) and an example `config.yaml`. The pattern is **one array task
per subject**: SLURM provides the across-subject parallelism, and each task lets
ANTs use all of its allocated cores.

```bash
mkdir -p logs
sbatch slurm/submit.sbatch slurm/config.yaml
```

The template reads the subject list from the config's `slurm.subjects`, injects
the right subject per array index, and caps ITK/OpenMP threads to
`--cpus-per-task`. Edit the `#SBATCH` resource directives (and the `--array`
range to match the number of subjects), the `module load` line (must be a
**Python 3.11** build), and the virtual-environment path before submitting.

## Tests

```bash
pytest
```

## Development

Contributions are welcome. For development setup, the check suite, PR
conventions, and how releases are automated, see
[CONTRIBUTING.md](CONTRIBUTING.md).

## BIDS app

MReyeXtract reads and writes BIDS-compatible layouts: it queries BOLD files with
[PyBIDS](https://github.com/bids-standard/pybids), honours BIDS entity filters,
and emits a `derivatives/mreyextract/` folder with a `dataset_description.json`.

## Correspondence

If you have questions, comments or inquiries, please reach out to us:
z.b.nudelman[at]vu.nl; m.nau[at]vu.nl
