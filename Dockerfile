# 1. Django 6.x 호환 Python 3.12 슬림 베이스 이미지
FROM python:3.12-slim

# 2. 실시간 로깅 및 캐시 최적화
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# 3. Java(KoNLPy/JPype1 필수) 및 C/C++ 컴파일 도구 사전 설치
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    gcc \
    g++ \
    cmake \
    pkg-config \
    libffi-dev \
    libssl-dev \
    python3-dev \
    curl \
    default-jdk \
    && rm -rf /var/lib/apt/lists/*

# Java 환경 변수 등록
ENV JAVA_HOME=/usr/lib/jvm/default-java
ENV PATH="${JAVA_HOME}/bin:${PATH}"

# 4. 컨테이너 내부 작업 디렉토리 설정
WORKDIR /app

# 5. pip 최신화 및 의존성 패키지 설치
# --prefer-binary: 소스 컴파일 충돌 방지를 위해 리눅스용 빌드 완료본 우선 다운로드
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip setuptools wheel && \
    pip install --no-cache-dir --prefer-binary -r requirements.txt

# 6. 소스 코드 전체 복사 (.dockerignore 적용)
COPY . .

# 7. manage.py가 위치한 디렉토리로 이동
WORKDIR /app/backend

# 8. 컨테이너 개방 포트 명시
EXPOSE 8000

# 9. 서버 실행 명령어
CMD ["python", "manage.py", "runserver", "0.0.0.0:8000"]