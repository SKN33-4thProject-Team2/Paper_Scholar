#!/usr/bin/env bash
# Usage: sudo bash scripts/deploy_backend.sh IMAGE --env-file .env
set -euo pipefail
image=$1
shift
container=paper-scholar
previous=paper-scholar-previous
# Validate schema and configuration before touching the healthy old service.
docker run --rm "$@" -e DEBUG=False "$image" python manage.py migrate --noinput
docker run --rm "$@" -e DEBUG=False "$image" python manage.py check
# Only remove the old rollback slot after preflight succeeds.
if docker container inspect "$previous" >/dev/null 2>&1; then
  docker rm -f "$previous"
fi
if docker container inspect "$container" >/dev/null 2>&1; then
  docker stop "$container"
  docker rename "$container" "$previous"
fi
rollback() {
  docker rm -f "$container" >/dev/null 2>&1 || true
  if docker container inspect "$previous" >/dev/null 2>&1; then
    docker rename "$previous" "$container"
    docker start "$container"
  fi
}
trap rollback ERR
# Keep the application and generated caches in named volumes across releases.
docker run -d --name "$container" --restart always \
  -p 127.0.0.1:8000:8000 \
  -v paper-scholar-data:/app/data -v paper-scholar-papers:/app/papers \
  "$@" -e DEBUG=False "$image"
healthy=false
for attempt in {1..30}; do
  if curl --fail --silent --max-time 3 http://127.0.0.1:8000/api/ready/ >/dev/null; then
    healthy=true
    break
  fi
  sleep 2
done
if [[ "$healthy" != true ]]; then
  echo "새 서비스가 정상 응답하지 않아 이전 컨테이너로 복구합니다." >&2
  false
fi
trap - ERR
# Keep the prior container/image for manual rollback until the next deployment.
echo "백엔드 서비스 및 DB 연결 확인 완료"
