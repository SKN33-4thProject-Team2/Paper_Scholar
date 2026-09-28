#!/bin/bash
set -e

PROJECT_DIR="/home/ubuntu/Paper_Scholar"
CONTAINER_NAME="paper-scholar"
IMAGE_NAME="paper-scholar:latest"

echo "[1/4] 최신 소스 코드 동기화 중..."
cd "$PROJECT_DIR"
git pull origin main

echo "[2/4] Docker 캐시를 활용한 증분 빌드..."
# Dockerfile의 레이어 분리 구조를 활용해 변경된 소스 코드만 5~10초 내에 빌드
docker build -t "$IMAGE_NAME" .

echo "[3/4] DB 검증 및 백엔드 교체..."
bash scripts/deploy_backend.sh "$IMAGE_NAME" --env-file .env

echo "[5/5] 프론트엔드 빌드 및 배치..."
# nginx가 /var/www/paper-scholar 를 서빙하도록 설정돼 있어야 반영된다.
if command -v npm >/dev/null 2>&1; then
  (
    cd frontend
    # package-lock.json이 그대로면 이미 받은 의존성을 그대로 쓴다.
    # 해시를 구하지 못하면 건너뛰지 않고 반드시 설치한다. 빈 해시를 기록해두면
    # 이후 배포에서 lock이 바뀌어도 계속 건너뛰게 되기 때문이다.
    LOCK_HASH="$(sha256sum package-lock.json 2>/dev/null | cut -d' ' -f1)"
    STAMP_FILE="node_modules/.deploy-lock-hash"
    if [ -n "$LOCK_HASH" ] \
      && [ -d node_modules ] \
      && [ -f "$STAMP_FILE" ] \
      && [ "$(cat "$STAMP_FILE")" = "$LOCK_HASH" ]; then
      echo "  의존성 변경 없음 - 설치를 건너뜁니다."
    else
      npm ci
      if [ -n "$LOCK_HASH" ]; then
        echo "$LOCK_HASH" > "$STAMP_FILE"
      else
        echo "  경고: package-lock.json 해시를 구하지 못해 다음 배포에서도 설치합니다."
        rm -f "$STAMP_FILE"
      fi
    fi
    npm run build
  )
  sudo mkdir -p /var/www/paper-scholar
  sudo rm -rf /var/www/paper-scholar/*
  sudo cp -r frontend/dist/* /var/www/paper-scholar/
  sudo chown -R www-data:www-data /var/www/paper-scholar || true
else
  echo "  npm이 없어 프론트엔드 빌드를 건너뜁니다 (GitHub Actions 배포를 사용하세요)."
fi

echo "=== 배포가 성공적으로 완료되었습니다 ==="