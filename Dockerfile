# 1. 파이썬 경량 베이스 이미지 선택
FROM python:3.12-slim

# 2. 파이썬 출력 버퍼링 및 pyc 생성 방지 설정
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

# 3. 작업 디렉터리 설정
WORKDIR /app

# 4. 필수 의존성 파일 복사 및 패키지 설치
COPY requirements.txt /app/
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# 5. 프로젝트 전체 소스코드 복사
COPY . /app/

# 6. Django 기본 포트 노출
EXPOSE 8000

# 7. 서버 실행 스크립트 실행 (또는 python manage.py runserver 0.0.0.0:8000)
CMD ["python", "manage.py", "runserver", "0.0.0.0:8000"]