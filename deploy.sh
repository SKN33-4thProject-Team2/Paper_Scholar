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

echo "[4/4] 데이터베이스 마이그레이션 및 찌꺼기 이미지 정리..."
docker exec "$CONTAINER_NAME" python manage.py migrate --noinput
# 빌드 캐시는 온전히 유지하고 이름 없는 태그 찌꺼기(dangling)만 정리
docker image prune -f

echo "=== 배포가 성공적으로 완료되었습니다 ==="