# 1. Ubuntu 20.04 (Focal Fossa) 기반의 Playwright 이미지를 사용합니다.
FROM mcr.microsoft.com/playwright:v1.44.0-focal

# 2. 작업 디렉토리 설정
WORKDIR /app

# 3. [핵심 수정] Python 3.9 및 빌드에 필요한 필수 도구들을 함께 설치합니다.
# python3.9-dev 와 build-essential 패키지를 추가하여 C 확장 모듈 컴파일 오류를 방지합니다.
RUN apt-get update && \
    apt-get install -y \
    python3.9 \
    python3.9-dev \
    python3-pip \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# 4. 프로젝트 파일 복사 (requirements.txt 먼저)
COPY requirements.txt .

# 5. requirements.txt 로 Python 라이브러리 설치
RUN python3.9 -m pip install --no-cache-dir -r requirements.txt

# 6. Playwright 라이브러리와 이미지에 내장된 브라우저를 연결합니다.
RUN python3.9 -m playwright install --with-deps chromium

# 7. 나머지 소스 코드 복사
COPY . .

# 8. API 서버가 사용할 포트 지정
EXPOSE 8000

# 9. 서버 실행 명령어
CMD ["python3.9", "-m", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]