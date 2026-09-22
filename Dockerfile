# 1. Django 6.x 호환 Python 3.12 슬림 베이스 이미지
FROM python:3.12-slim

# 2. 파이썬 버퍼링 해제 및 바이트코드(.pyc) 생성 방지
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# 3. KoNLPy/JPype1용 OpenJDK 및 C/C++ 컴파일 빌드 도구 사전 설치
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

# 5. pip 기본 도구 최신화
RUN pip install --no-cache-dir --upgrade pip setuptools wheel

# 6. CPU 전용 PyTorch 사전 설치 (requirements.txt보다 먼저 설치하여 캐시 고정)
RUN pip install --no-cache-dir \
    torch torchvision torchaudio \
    --index-url https://download.pytorch.org/whl/cpu

# 7. 프로젝트 의존성 파일 복사 및 설치 (requirements가 바뀌어도 위 PyTorch 캐시는 유지)
COPY requirements.txt .
RUN pip install --no-cache-dir --prefer-binary -r requirements.txt

# 8. 소스 코드 전체 복사 (.dockerignore 적용)
COPY . .

# 비동기 요약·번역 worker가 사용하는 공통 로거가 이미지에 포함됐는지
# 배포 전에 검증한다. ``log/``가 실수로 ignore되면 빌드 단계에서 실패한다.
RUN python -c "from log import AppLogger, LogCode"

# 9. manage.py가 위치한 backend 디렉토리로 작업 경로 이동
WORKDIR /app/backend

# 10. 컨테이너 개방 포트 명시
EXPOSE 8000

# 11. Django 웹 서버 실행 (0.0.0.0 바인딩)
CMD ["python", "manage.py", "runserver", "0.0.0.0:8000"]
