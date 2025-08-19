# main.py (봇 탐지 우회 기능이 강화된 최종 버전)
import asyncio
import re
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from playwright.async_api import async_playwright, Page, Browser
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
        await page.wait_for_load_state('networkidle', timeout=5000)  # 네트워크 안정화 대기

        label = page.locator("*:has-text('매물 최저가')").first
        if await label.count() > 0:
            price_area = label.locator("..").locator(".price-info-area .price-area .txt")
            if await price_area.count() > 0:
                price_text = await price_area.first.text_content()
                if price_text and ('억' in price_text or '만' in price_text):
                    return to_won(price_text.strip())

        price_elements = page.locator(".price-info-area .price-area .txt").all()
        for el in await price_elements:
            price_text = await el.text_content()
            if price_text and ('억' in price_text or '만' in price_text):
                price = to_won(price_text.strip())
                if price > 0: return price
    except Exception as e:
        print(f"가격 추출 중 오류: {e}")
    return None


async def fetch_lowest_by_address(address: str) -> LowestPriceDto:
    async with async_playwright() as p:
        browser: Browser = await p.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-dev-shm-usage"]
        )

        # 실제 사람처럼 보이게 하는 브라우저 컨텍스트 설정
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/114.0.0.0 Safari/537.36",
            java_script_enabled=True,
            viewport={'width': 1920, 'height': 1080}
        )
        page: Page = await context.new_page()
        base_url = "https://www.bdsplanet.com"

        page.set_default_timeout(30000)

        try:
            # 1. 사이트 접속
            await page.goto(f"{base_url}/main.ytp", wait_until="domcontentloaded", timeout=20000)

            # 2. 검색 실행
            search_input = page.locator("input#searchInput").first
            await search_input.wait_for(state="visible", timeout=10000)

            # 사람처럼 타이핑
            await search_input.type(address, delay=100)
            await page.wait_for_timeout(500)
            await search_input.press("Enter")

            # 3. 자동완성 목록 클릭 (더 안정적인 방법)
            first_result_selector = "ul.d_list > li.list_item > a"
            first_result = page.locator(first_result_selector).first

            await first_result.wait_for(state="visible", timeout=10000)
            await first_result.click()

            # 페이지가 완전히 로드될 때까지 기다림
            await page.wait_for_load_state("networkidle", timeout=15000)

            # 4. URL 분석 및 가격 추출
            current_url = page.url
            match = re.search(r"(/map/realprice_map/[^/]+/N/[ABC]/)([12])(/[^/]+\.ytp)", current_url)

            if match:
                base_pattern, _, suffix = match.groups()

                # 매매
                sale_url = f"{base_url}{base_pattern}1{suffix}"
                await page.goto(sale_url, wait_until="domcontentloaded")
                sale_price = await extract_price(page)

                # 전세
                rent_url = f"{base_url}{base_pattern}2{suffix}"
                await page.goto(rent_url, wait_until="domcontentloaded")
                rent_price = await extract_price(page)

                return LowestPriceDto(address=address, salePrice=sale_price, rentPrice=rent_price, sourceUrl=sale_url)
            else:
                # [디버깅용] 에러 발생 시 스크린샷 저장
                await page.screenshot(path="error_screenshot.png")
                print(f"URL 패턴 분석 실패. 현재 URL: {current_url}")
                return LowestPriceDto(address=address, error=f"URL 패턴 분석 실패: {current_url}")

        except Exception as e:
            await page.screenshot(path="error_screenshot.png")
            print(f"크롤링 전체 과정에서 오류 발생: {e}")
            return LowestPriceDto(address=address, error=f"크롤링 오류: {e}")
        finally:
            await browser.close()


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