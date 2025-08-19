# main.py (Playwright 최종 버전)
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

# --- 크롤링 로직 (Playwright) ---
async def extract_price(page: Page) -> Union[int, None]:
    try:
        # "매물 최저가" 라벨 기준 탐색
        label = page.locator("*:has-text('매물 최저가')").first
        if await label.count() > 0:
            price_area = label.locator("..").locator(".price-info-area .price-area .txt")
            if await price_area.count() > 0:
                price_text = await price_area.first.text_content()
                if price_text and ('억' in price_text or '만' in price_text):
                    return to_won(price_text.strip())

        # 일반적인 가격 영역 탐색
        price_elements = page.locator(".price-info-area .price-area .txt").all()
        for el in await price_elements:
            price_text = await el.text_content()
            if price_text and ('억' in price_text or '만' in price_text):
                price = to_won(price_text.strip())
                if price > 0:
                    return price
    except Exception as e:
        print(f"가격 추출 중 오류: {e}")
    return None

async def fetch_lowest_by_address(address: str) -> LowestPriceDto:
    async with async_playwright() as p:
        browser: Browser = await p.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-dev-shm-usage"]
        )
        page: Page = await browser.new_page()
        base_url = "https://www.bdsplanet.com"

        try:
            # 1. 사이트 접속
            await page.goto(f"{base_url}/main.ytp", wait_until="domcontentloaded")
            await page.wait_for_timeout(500)

            # 2. 검색 실행
            search_input_selectors = [
                "input[placeholder*='주소']", "input[placeholder*='검색']",
                "input[type='search']", "input[type='text']"
            ]
            search_input = None
            for selector in search_input_selectors:
                locator = page.locator(selector).first
                if await locator.is_visible():
                    search_input = locator
                    break

            if not search_input: raise Exception("검색창을 찾을 수 없습니다.")

            await search_input.fill(address)
            await page.wait_for_timeout(300)
            await search_input.press("Enter")
            await page.wait_for_timeout(1200)

            # 3. URL 분석 및 가격 추출
            current_url = page.url
            match = re.search(r"(/map/realprice_map/[^/]+/N/[ABC]/)([12])(/[^/]+\.ytp)", current_url)

            if match:
                base_pattern, _, suffix = match.groups()

                # 매매
                sale_url = f"{base_url}{base_pattern}1{suffix}"
                await page.goto(sale_url, wait_until="domcontentloaded")
                await page.wait_for_timeout(1000)
                sale_price = await extract_price(page)

                # 전세
                rent_url = f"{base_url}{base_pattern}2{suffix}"
                await page.goto(rent_url, wait_until="domcontentloaded")
                await page.wait_for_timeout(1000)
                rent_price = await extract_price(page)

                return LowestPriceDto(address=address, salePrice=sale_price, rentPrice=rent_price, sourceUrl=sale_url)
            else:
                return LowestPriceDto(address=address, error=f"URL 패턴 분석 실패: {current_url}")

        except Exception as e:
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