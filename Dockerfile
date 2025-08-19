# Dockerfile (Playwright 공식 이미지 사용 - 최종)

# 1. Playwright 공식 Python 이미지를 베이스로 사용합니다.
# 이 이미지에는 Python, Playwright, 브라우저 및 모든 의존성이 포함되어 있습니다.
FROM mcr.microsoft.com/playwright/python:v1.44.0-jammy

# 2. 작업 디렉토리 설정
WORKDIR /app

# 3. 프로젝트 파일 복사
COPY . .

# 4. requirements.txt 로 Python 라이브러리 설치
RUN pip install --no-cache-dir -r requirements.txt

# 5. API 서버가 사용할 포트 지정
EXPOSE 8000

# 6. 서버 실행 명령어
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]