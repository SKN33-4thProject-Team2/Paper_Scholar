#!/usr/bin/env bash
set -euo pipefail
cd /app/backend
# A failed worker must restart the container as well, so pending jobs cannot
# silently accumulate while only the web process remains healthy.
python manage.py run_jobs &
worker_pid=$!
gunicorn django_config.wsgi:application --bind 0.0.0.0:8000 \
  --workers "${WEB_WORKERS:-2}" --threads 4 --timeout 180 \
  --access-logfile - --error-logfile - &
web_pid=$!
shutdown() {
  kill -TERM "$worker_pid" "$web_pid" 2>/dev/null || true
  wait "$worker_pid" "$web_pid" 2>/dev/null || true
}
trap shutdown EXIT
trap 'exit 143' TERM INT
set +e
wait -n "$worker_pid" "$web_pid"
exit_code=$?
set -e
if [[ "$exit_code" -eq 0 ]]; then exit_code=1; fi
exit "$exit_code"
