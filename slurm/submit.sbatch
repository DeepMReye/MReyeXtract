#!/bin/bash
#SBATCH --job-name=mreyextract
#SBATCH --partition=defq
#SBATCH --time=02:00:00
#SBATCH --cpus-per-task=4
#SBATCH --mem=16G
#SBATCH --array=0-3                      # MUST match the number of subjects below
#SBATCH --output=logs/%x-%A_%a.out
#SBATCH --error=logs/%x-%A_%a.err
#
# One array task per subject. Pipeline options come from the YAML config;
# resources come from the #SBATCH directives above (edit them, or override on
# the command line, since sbatch flags beat #SBATCH lines).
#
# Usage:
#   mkdir -p logs
#   sbatch slurm/submit.sbatch slurm/config.yaml
#
# To size the array to the config automatically:
#   N=$(python -c "import yaml,sys;print(len(yaml.safe_load(open('slurm/config.yaml'))['slurm']['subjects']))")
#   sbatch --array=0-$((N-1)) slurm/submit.sbatch slurm/config.yaml

set -euo pipefail

CONFIG="${1:?Usage: sbatch submit.sbatch <config.yaml>}"

module load 2025
module load Python/3.11.x-GCCcore-13.3.0   # must be a Python 3.11 build

# Activate the environment that has mreyextract installed.
source /abs/path/to/.venv/bin/activate

# Pick this task's subject: slurm.subjects[SLURM_ARRAY_TASK_ID].
SUBJECT=$(python - "$CONFIG" "$SLURM_ARRAY_TASK_ID" <<'PY'
import sys, yaml
cfg = yaml.safe_load(open(sys.argv[1]))
subjects = cfg.get("slurm", {}).get("subjects", [])
print(subjects[int(sys.argv[2])])
PY
)

# Keep every threading layer inside the allocation.
export ITK_GLOBAL_DEFAULT_NUMBER_OF_THREADS="$SLURM_CPUS_PER_TASK"
export OMP_NUM_THREADS="$SLURM_CPUS_PER_TASK"

echo "== Job ${SLURM_JOB_ID} task ${SLURM_ARRAY_TASK_ID} -> subject ${SUBJECT} on ${SLURMD_NODENAME}"

# One subject per task, so let ANTs use all allocated cores (n_jobs=1). This
# overrides any n_jobs/threads_per_job in the config, which is the right pattern
# for array-based sharding.
mreyextract --config "$CONFIG" \
    --subject "$SUBJECT" \
    --n-jobs 1 \
    --threads-per-job "$SLURM_CPUS_PER_TASK"
