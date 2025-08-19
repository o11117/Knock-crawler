# main.py (bdsplanet.com 크롤링 + 스텔스 모드)
import asyncio
import re
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from playwright.async_api import async_playwright, Page, Browser, TimeoutError as PlaywrightTimeoutError
from playwright_stealth import stealth_async  # 스텔스 라이브러리 임포트
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
                        if price > 0: return price
    except Exception as e:
        print(f"가격 추출 중 오류: {e}")
    return None


async def fetch_lowest_by_address(address: str) -> LowestPriceDto:
    async with async_playwright() as p:
        browser: Browser = await p.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-dev-shm-usage", "--disable-gpu"]
        )
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

        # --- ▼▼▼▼▼ 스텔스 모드 적용 ▼▼▼▼▼ ---
        await stealth_async(page)
        print("[로그] 스텔스 모드가 적용되었습니다.")
        # --- ▲▲▲▲▲ 스텔스 모드 적용 ▲▲▲▲▲ ---

        base_url = "https://www.bdsplanet.com"
        page.set_default_timeout(30000)

        try:
            await page.goto(f"{base_url}/main.ytp", wait_until="domcontentloaded", timeout=20000)
            search_input_selectors = [
                "input#searchInput", "input[placeholder*='주소']", "input[placeholder*='검색']",
                "input[type='search']", "input[type='text']"
            ]
            search_input = None
            for selector in search_input_selectors:
                locator = page.locator(selector).first
                try:
                    await locator.wait_for(state="visible", timeout=3000)
                    search_input = locator
                    print(f"검색창 찾음: {selector}")
                    break
                except PlaywrightTimeoutError:
                    continue
            if not search_input: raise Exception("검색창을 찾을 수 없습니다.")

            await search_input.type(address, delay=150)
            await page.wait_for_timeout(500)
            await search_input.press("Enter")

            first_result_selector = "ul.d_list > li.list_item > a"
            first_result = page.locator(first_result_selector).first
            await first_result.wait_for(state="visible", timeout=10000)
            await first_result.click()
            await page.wait_for_load_state("networkidle", timeout=15000)

            current_url = page.url
            match = re.search(r"(/map/realprice_map/[^/]+/N/[ABC]/)([12])(/[^/]+\.ytp)", current_url)

            if match:
                base_pattern, _, suffix = match.groups()
                sale_url = f"{base_url}{base_pattern}1{suffix}"
                await page.goto(sale_url, wait_until="domcontentloaded")
                sale_price = await extract_price(page)
                rent_url = f"{base_url}{base_pattern}2{suffix}"
                await page.goto(rent_url, wait_until="domcontentloaded")
                rent_price = await extract_price(page)
                return LowestPriceDto(address=address, salePrice=sale_price, rentPrice=rent_price, sourceUrl=sale_url)
            else:
                return LowestPriceDto(address=address, error=f"URL 패턴 분석 실패: {current_url}")
        except Exception as e:
            error_message = str(e).splitlines()[0]
            return LowestPriceDto(address=address, error=f"크롤링 오류: {error_message}")
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