#!/bin/bash
set -e

DOMAIN="skn33-project.store"
EMAIL="admin@skn33-project.store"
PROJECT_DIR="/home/ubuntu/Paper_Scholar"

echo "[1/5] 필수 시스템 패키지 및 Certbot 설치 확인..."
sudo apt update -y
sudo apt install -y certbot python3-certbot-nginx nginx

echo "[2/5] 파이썬 가상환경 및 의존성 동기화..."
cd "$PROJECT_DIR"
if [ ! -d ".venv" ]; then
    python3 -m venv .venv
fi
source .venv/bin/activate
pip install -r requirements.txt

echo "[3/5] Nginx 설정 파일 자동 교체 및 리로드..."
sudo cp "$PROJECT_DIR/nginx/app.conf" /etc/nginx/sites-available/paper_scholar.conf
sudo ln -sf /etc/nginx/sites-available/paper_scholar.conf /etc/nginx/sites-enabled/
sudo rm -f /etc/nginx/sites-enabled/default
sudo nginx -t
sudo systemctl reload nginx

echo "[4/5] Let's Encrypt SSL 자동 발급 및 443 HTTPS 자동 바인딩..."
# SSL 인증서가 없거나 갱신 필요 시 certbot이 nginx 설정을 443으로 자동 갱신
sudo certbot --nginx -d "$DOMAIN" --non-interactive --agree-tos -m "$EMAIL" --redirect

echo "[5/5] 백엔드/프론트엔드 Systemd 서비스 재시작..."
sudo systemctl restart paper-backend.service
sudo systemctl restart paper-frontend.service

echo "=== 배포 및 인프라 프로비저닝 완료 ==="