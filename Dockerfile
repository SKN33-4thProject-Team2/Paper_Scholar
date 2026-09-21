# 1. Django 6.x 호환을 위한 Python 3.12 슬림 리눅스 환경 사용
FROM python:3.12-slim

# 2. 파이썬 버퍼링 해제 (컨테이너 내부 로그 실시간 출력)
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# 3. 컨테이너 내부 작업 디렉토리 설정
WORKDIR /app

# 4. pip 최신화 및 패키지 설치
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# 5. 소스 코드 전체 복사 (.dockerignore 파일 자동 제외)
COPY . .

# 6. manage.py가 있는 backend 디렉토리로 작업 경로 이동
WORKDIR /app/backend

# 7. Django 기본 포트 명시
EXPOSE 8000

# 8. 컨테이너 실행 명령어 (외부 접속 허용 0.0.0.0 바인딩)
CMD ["python", "manage.py", "runserver", "0.0.0.0:8000"]
