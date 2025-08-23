# main.py (Firefox 사용 버전)
import asyncio
import re
import time
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from playwright.async_api import async_playwright, Page, Browser, TimeoutError
from typing import Union
from money_parser import to_won

app = FastAPI()


class LowestPriceDto(BaseModel):
    address: str
    salePrice: Union[int, None] = None
    rentPrice: Union[int, None] = None
    sourceUrl: Union[str, None] = None
    error: Union[str, None] = None


async def extract_price(page: Page) -> Union[int, None]:
    try:
        await page.wait_for_selector(".price-info-area", timeout=7000)
        label = page.locator("*:has-text('매물 최저가')").first
        if await label.count() > 0:
            price_area = label.locator("..").locator(".price-info-area .price-area .txt")
            if await price_area.count() > 0:
                price_text = await price_area.first.text_content()
                if price_text and ('억' in price_text or '만' in price_text):
                    return to_won(price_text.strip())
        price_elements = await page.locator(".price-info-area .price-area .txt").all()
        for el in price_elements:
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

        # 프록시 설정은 그대로 둡니다 (필요시 주석 해제하여 사용)
        # proxy_settings = {
        #     "server": "http://YOUR_PROXY_IP:YOUR_PROXY_PORT",
        #     "username": "YOUR_USERNAME",
        #     "password": "YOUR_PASSWORD"
        # }

        # ✨ [수정] p.chromium.launch를 p.firefox.launch로 변경합니다.
        browser: Browser = await p.firefox.launch(
            headless=True
            # proxy=proxy_settings # 프록시 사용 시 이 줄의 주석을 해제하세요.
        )
        context = await browser.new_context(
            user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:125.0) Gecko/20100101 Firefox/125.0',
            # Firefox User-Agent
            viewport={'width': 1920, 'height': 1080},
            locale='ko-KR'
        )
        page: Page = await context.new_page()
        base_url = "https://www.bdsplanet.com"

        try:
            await page.goto(f"{base_url}/main.ytp", wait_until="networkidle", timeout=90000)

            search_input = page.locator("input[placeholder*='주소'], input[placeholder*='검색']").first
            await search_input.wait_for(state="visible", timeout=10000)
            await search_input.fill(address)
            await search_input.press("Enter")

            expected_url_pattern = re.compile(r"/map/realprice_map/[^/]+/N/[ABC]/")
            end_time = time.time() + 15
            final_url = None
            while time.time() < end_time:
                current_url = page.url
                if expected_url_pattern.search(current_url):
                    final_url = current_url
                    break
                await asyncio.sleep(0.5)

            if not final_url:
                raise TimeoutError(f"15초 내에 검색 결과 페이지로 이동하지 못했습니다. 현재 URL: {page.url}")

            match = re.search(r"(/map/realprice_map/[^/]+/N/[ABC]/)([12])(/[^/]+\.ytp.*)", final_url)
            if match:
                base_pattern, _, suffix = match.groups()
                sale_url = f"{base_url}{base_pattern}1{suffix}"
                rent_url = f"{base_url}{base_pattern}2{suffix}"

                await page.goto(sale_url, wait_until="domcontentloaded")
                sale_price = await extract_price(page)

                await page.goto(rent_url, wait_until="domcontentloaded")
                rent_price = await extract_price(page)

                return LowestPriceDto(address=address, salePrice=sale_price, rentPrice=rent_price, sourceUrl=sale_url)
            else:
                return LowestPriceDto(address=address, error=f"URL 패턴 분석 실패: {final_url}")

        except Exception as e:
            return LowestPriceDto(address=address, error=f"크롤링 오류 발생: {e}")
        finally:
            await context.close()
            await browser.close()


@app.get("/crawl", response_model=LowestPriceDto)
async def crawl_real_estate(address: str):
    if not address:
        raise HTTPException(status_code=400, detail="주소를 입력해주세요.")
    return await fetch_lowest_by_address(address)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)