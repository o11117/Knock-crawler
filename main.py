# main.py (검색 버튼 클릭 로직 추가 최종 버전)
import asyncio
import re
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from playwright.async_api import async_playwright, Page, Browser, TimeoutError as PlaywrightTimeoutError
from typing import Union
from money_parser import to_won

# --- FastAPI 앱 설정 ---
app = FastAPI()


# --- 데이터 모델 ---
class LowestPriceDto(BaseModel):
    address: str
    salePrice: Union[int, None] = None
    rentPrice: Union[int, None] = None
    sourceUrl: Union[str, None] = None
    error: Union[str, None] = None


# --- 크롤링 로직 ---
async def extract_price(page: Page) -> Union[int, None]:
    try:
        print("[로그] 가격 추출 시작...")
        await page.wait_for_load_state('networkidle', timeout=7000)

        selectors = [
            "*:has-text('매물 최저가') >> .. >> .price-info-area .price-area .txt",
            ".price-info-area .price-area .txt",
        ]
        for selector in selectors:
            elements = await page.locator(selector).all()
            for el in elements:
                if await el.is_visible():
                    price_text = await el.text_content()
                    if price_text and ('억' in price_text or '만' in price_text):
                        price = to_won(price_text.strip())
                        if price > 0:
                            print(f"[로그] 가격 추출 성공: {price}")
                            return price
        print("[로그] 페이지에서 가격 정보를 찾지 못했습니다.")
    except Exception as e:
        print(f"[오류] 가격 추출 중 오류 발생: {e}")
    return None


async def fetch_lowest_by_address(address: str) -> LowestPriceDto:
    print("\n--- [로그] 새로운 크롤링 요청 시작 ---")
    print(f"[로그] 요청 주소: {address}")
    async with async_playwright() as p:
        browser: Browser = await p.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-dev-shm-usage", "--disable-gpu"]
        )
        print("[로그] Playwright 브라우저 시작 완료")

        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/114.0.0.0 Safari/537.36",
            java_script_enabled=True,
            viewport={'width': 1920, 'height': 1080},
            extra_http_headers={
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7",
                "Accept-Encoding": "gzip, deflate, br",
                "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
                "Sec-Fetch-Dest": "document", "Sec-Fetch-Mode": "navigate",
                "Sec-Fetch-Site": "none", "Sec-Fetch-User": "?1",
                "Upgrade-Insecure-Requests": "1"
            }
        )
        page: Page = await context.new_page()
        base_url = "https://www.bdsplanet.com"
        page.set_default_timeout(30000)
        print("[로그] 브라우저 컨텍스트 및 페이지 생성 완료")

        try:
            print("[로그] 1. 사이트 접속 시도...")
            await page.goto(f"{base_url}/main.ytp", wait_until="domcontentloaded", timeout=20000)
            print("[로그] 1. 사이트 접속 성공")

            print("[로그] 2. 검색창 탐색 시작...")
            search_input = page.locator("input#searchInput").first
            await search_input.wait_for(state="visible", timeout=5000)
            print("[로그] 2. 검색창 찾음")

            await search_input.type(address, delay=100)
            await page.wait_for_timeout(200)

            # --- ▼▼▼▼▼ 핵심 수정 부분 ▼▼▼▼▼ ---
            # Enter 키 대신 검색 버튼을 직접 클릭합니다.
            print("[로그] 2a. 검색 버튼 클릭 시도...")
            search_button = page.locator("button.btn_search").first
            await search_button.click()
            print("[로그] 2a. 검색 버튼 클릭 성공")
            # --- ▲▲▲▲▲ 핵심 수정 부분 ▲▲▲▲▲ ---

            print("[로그] 3. 검색 후 페이지 이동 및 로딩 대기...")
            await page.wait_for_load_state("networkidle", timeout=15000)
            print("[로그] 3. 페이지 로딩 완료")

            current_url = page.url
            print(f"[로그] 4. 현재 URL: {current_url}")
            match = re.search(r"(/map/realprice_map/[^/]+/N/[ABC]/)([12])(/[^/]+\.ytp)", current_url)

            if match:
                print("[로그] 4. URL 패턴 분석 성공")
                base_pattern, _, suffix = match.groups()

                sale_url = f"{base_url}{base_pattern}1{suffix}"
                print(f"[로그] 4a. 매매 정보 페이지로 이동: {sale_url}")
                await page.goto(sale_url, wait_until="domcontentloaded")
                sale_price = await extract_price(page)

                rent_url = f"{base_url}{base_pattern}2{suffix}"
                print(f"[로그] 4b. 전세 정보 페이지로 이동: {rent_url}")
                await page.goto(rent_url, wait_until="domcontentloaded")
                rent_price = await extract_price(page)

                print("[로그] 크롤링 최종 성공")
                return LowestPriceDto(address=address, salePrice=sale_price, rentPrice=rent_price, sourceUrl=sale_url)
            else:
                print("[오류] 4. URL 패턴 분석 실패")
                return LowestPriceDto(address=address, error=f"URL 패턴 분석 실패: {current_url}")

        except Exception as e:
            error_message = str(e).splitlines()[0]
            print(f"[오류] 크롤링 전체 과정에서 오류 발생: {error_message}")
            return LowestPriceDto(address=address, error=f"크롤링 오류: {error_message}")
        finally:
            await browser.close()
            print("[로그] 브라우저 종료 및 자원 정리 완료")


# --- API 엔드포인트 ---
@app.get("/crawl", response_model=LowestPriceDto)
async def crawl_real_estate(address: str):
    if not address:
        raise HTTPException(status_code=400, detail="주소를 입력해주세요.")
    return await fetch_lowest_by_address(address)


# --- 서버 실행 ---
if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)