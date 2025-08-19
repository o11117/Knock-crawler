# Dockerfile (Playwright 브라우저 연결 문제 해결)

# 1. Playwright 공식 Python 이미지를 베이스로 사용합니다.
FROM mcr.microsoft.com/playwright/python:v1.44.0-jammy

# 2. 작업 디렉토리 설정
WORKDIR /app

# 3. 프로젝트 파일 복사 (requirements.txt 먼저)
COPY requirements.txt .

# 4. requirements.txt 로 Python 라이브러리 설치
RUN pip install --no-cache-dir -r requirements.txt

# 5. [핵심 수정 부분] Playwright 라이브러리와 이미지에 내장된 브라우저를 연결합니다.
# --with-deps 옵션은 필요한 모든 시스템 의존성을 함께 설치해줍니다.
RUN python -m playwright install --with-deps chromium

# 6. 나머지 소스 코드 복사
COPY . .

# 7. API 서버가 사용할 포트 지정
EXPOSE 8000

# 8. 서버 실행 명령어
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]