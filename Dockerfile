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

# 5. pip 최신화 및 의존성 패키지 단계별 설치
COPY requirements.txt .
# pip, setuptools, wheel 최신화
RUN pip install --no-cache-dir --upgrade pip setuptools wheel

# CPU 전용 PyTorch 사전 설치 (수 GB에 달하는 CUDA 드라이버 유입 및 디스크 부족 방지)
RUN pip install --no-cache-dir torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cpu

# 나머지 모든 프로젝트 의존성 설치
RUN pip install --no-cache-dir --prefer-binary -r requirements.txt

# 6. 소스 코드 전체 복사 (.dockerignore 적용)
COPY . .

# 7. manage.py가 위치한 backend 디렉토리로 작업 경로 이동
WORKDIR /app/backend

# 8. 컨테이너 개방 포트 명시
EXPOSE 8000

# 9. Django 웹 서버 실행 (0.0.0.0 바인딩)
CMD ["python", "manage.py", "runserver", "0.0.0.0:8000"]