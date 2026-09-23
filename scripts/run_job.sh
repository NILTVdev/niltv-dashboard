#!/usr/bin/env bash
# ============================================================
# Cron wrapper: loads env, activates venv, runs a Python job.
#
# Usage:
#   scripts/run_job.sh backend.jobs.run_zoomph
#
# Logs go to /tmp/niltv-<job>.log (last 5000 lines kept) and
# CloudWatch via watchtower inside the Python job.
# ============================================================
set -euo pipefail

APP_DIR="/home/ubuntu/niltv_dashboard"
VENV_DIR="$APP_DIR/venv"

JOB_MODULE="$1"
JOB_NAME="${JOB_MODULE##*.}"
LOG_FILE="/tmp/niltv-${JOB_NAME}.log"

# Load environment variables from .env
if [ -f "$APP_DIR/.env" ]; then
    set -a
    . "$APP_DIR/.env"
    set +a
fi

# Activate virtual environment
. "$VENV_DIR/bin/activate"

# Change to app directory (so pydantic Settings finds .env)
cd "$APP_DIR"

echo "==> [$JOB_NAME] Starting at $(date -u)" >> "$LOG_FILE"
python -m "$JOB_MODULE" "${@:2}" >> "$LOG_FILE" 2>&1
echo "==> [$JOB_NAME] Finished at $(date -u)" >> "$LOG_FILE"

# Keep log bounded to last 5000 lines
tail -n 5000 "$LOG_FILE" > "${LOG_FILE}.tmp" && mv "${LOG_FILE}.tmp" "$LOG_FILE"
