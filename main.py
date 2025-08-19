# main.py (disco.re 크롤링 최종 버전)
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
async def extract_prices(page: Page) -> dict:
    """상세 페이지에서 매매가와 전세가를 추출합니다."""
    print("[로그] 가격 추출 시작...")
    prices = {'sale': None, 'rent': None}
    try:
        # '실거래가' 탭이 로드될 때까지 대기
        await page.wait_for_selector("text='실거래가'", timeout=10000)

        # 거래 유형(매매, 전세)과 가격을 모두 포함하는 리스트 아이템을 찾음
        list_items = await page.locator("ul > li:has(span:text-matches('^(매매|전세)$'))").all()

        for item in list_items:
            # 거래 유형 텍스트 (매매 또는 전세)
            trade_type_element = item.locator("span").first
            trade_type = await trade_type_element.text_content()

            # 가격 텍스트
            price_element = item.locator("strong").first
            price_text = await price_element.text_content()

            if price_text:
                price_won = to_won(price_text.strip())
                if '매매' in trade_type and prices['sale'] is None:
                    prices['sale'] = price_won
                    print(f"[로그] 매매가 추출 성공: {price_won}")
                elif '전세' in trade_type and prices['rent'] is None:
                    prices['rent'] = price_won
                    print(f"[로그] 전세가 추출 성공: {price_won}")

        if prices['sale'] is None and prices['rent'] is None:
            print("[로그] 페이지에서 가격 정보를 찾지 못했습니다.")

    except Exception as e:
        print(f"[오류] 가격 추출 중 오류 발생: {e}")
    return prices


async def fetch_lowest_by_address(address: str) -> LowestPriceDto:
    print(f"\n--- [로그] 새로운 크롤링 요청 시작 (대상: disco.re) ---")
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
            viewport={'width': 1920, 'height': 1080}
        )
        page: Page = await context.new_page()
        base_url = "https://www.disco.re"
        page.set_default_timeout(35000)
        print("[로그] 브라우저 컨텍스트 및 페이지 생성 완료")

        try:
            print("[로그] 1. 사이트 접속 시도...")
            await page.goto(base_url, wait_until="load", timeout=25000)
            print("[로그] 1. 사이트 접속 성공")

            print("[로그] 2. 검색창 탐색 및 주소 입력...")
            search_input = page.locator("input[placeholder='주소를 입력하세요']").first
            await search_input.wait_for(state="visible", timeout=15000)
            await search_input.type(address, delay=100)
            await search_input.press("Enter")
            print("[로그] 2. 검색 실행 완료")

            print("[로그] 3. 검색 결과 목록 대기 및 첫번째 항목 클릭...")
            first_result_selector = "a[href*='/property/building/']"  # 건물 상세 페이지로 가는 링크
            first_result = page.locator(first_result_selector).first
            await first_result.wait_for(state="visible", timeout=15000)

            # 페이지 이동을 위해 클릭 후 로딩을 기다림
            await asyncio.gather(
                page.wait_for_load_state("networkidle", timeout=20000),
                first_result.click()
            )
            print("[로그] 3. 첫번째 결과 클릭 및 페이지 이동 완료")

            current_url = page.url
            print(f"[로그] 4. 현재 URL: {current_url}")

            if "/property/" not in current_url:
                raise Exception("상세 페이지로 이동하지 못했습니다.")

            prices = await extract_prices(page)

            print("[로그] 크롤링 최종 성공")
            return LowestPriceDto(
                address=address,
                salePrice=prices['sale'],
                rentPrice=prices['rent'],
                sourceUrl=current_url
            )

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