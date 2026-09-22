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

echo "[3/4] 백엔드 컨테이너 초고속 교체..."
docker stop "$CONTAINER_NAME" 2>/dev/null || true
docker rm "$CONTAINER_NAME" 2>/dev/null || true

# 외부 MySQL(IPTime) 및 호스트 네트워크와 안전하게 통신하도록 구동
docker run -d \
  --name "$CONTAINER_NAME" \
  --restart unless-stopped \
  -p 8000:8000 \
  --dns 8.8.8.8 --dns 8.8.4.4 \
  "$IMAGE_NAME"

echo "[4/5] 데이터베이스 마이그레이션 및 찌꺼기 이미지 정리..."
docker exec "$CONTAINER_NAME" python manage.py migrate --noinput
# 빌드 캐시는 온전히 유지하고 이름 없는 태그 찌꺼기(dangling)만 정리
docker image prune -f

echo "[5/5] 프론트엔드 빌드 및 배치..."
# nginx가 /var/www/paper-scholar 를 서빙하도록 설정돼 있어야 반영된다.
if command -v npm >/dev/null 2>&1; then
  (
    cd frontend
    # package-lock.json이 그대로면 이미 받은 의존성을 그대로 쓴다.
    LOCK_HASH="$(sha256sum package-lock.json | cut -d' ' -f1)"
    STAMP_FILE="node_modules/.deploy-lock-hash"
    if [ -d node_modules ] && [ -f "$STAMP_FILE" ] && [ "$(cat "$STAMP_FILE")" = "$LOCK_HASH" ]; then
      echo "  의존성 변경 없음 - 설치를 건너뜁니다."
    else
      npm ci
      echo "$LOCK_HASH" > "$STAMP_FILE"
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