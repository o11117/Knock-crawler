# 1. [수정] Ubuntu 20.04 (Focal Fossa) 기반의 Playwright 이미지를 사용합니다.
# 이 이미지는 Python 3.9와 호환성이 좋습니다.
FROM mcr.microsoft.com/playwright:v1.44.0-focal

# 2. 작업 디렉토리 설정
WORKDIR /app

# 3. [추가] Python 3.9 및 pip 설치
RUN apt-get update && \
    apt-get install -y python3.9 python3-pip && \
    rm -rf /var/lib/apt/lists/*

# 4. 프로젝트 파일 복사 (requirements.txt 먼저)
COPY requirements.txt .

# 5. requirements.txt 로 Python 라이브러리 설치
# python3.9 명령어로 명확하게 버전을 지정해줍니다.
RUN python3.9 -m pip install --no-cache-dir -r requirements.txt

# 6. [핵심 수정 부분] Playwright 라이브러리와 이미지에 내장된 브라우저를 연결합니다.
RUN python3.9 -m playwright install --with-deps chromium

# 7. 나머지 소스 코드 복사
COPY . .

# 8. API 서버가 사용할 포트 지정
EXPOSE 8000

# 9. 서버 실행 명령어
# 실행 시에도 python3.9를 사용하도록 변경합니다.
CMD ["python3.9", "-m", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]