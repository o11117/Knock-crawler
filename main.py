# main.py (URL 변화 관찰 및 디버깅 최종 버전)
import asyncio
import os
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
    # ... (extract_price 함수는 이전과 동일)
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
        # ... (프록시 설정은 동일)
        proxy_host = os.getenv("PROXY_HOST")
        proxy_port = os.getenv("PROXY_PORT")
        proxy_username = os.getenv("PROXY_USERNAME")
        proxy_password = os.getenv("PROXY_PASSWORD")

        proxy_settings = None
        if proxy_host and proxy_port:
            server = f"http://{proxy_host}:{proxy_port}"
            proxy_settings = {"server": server, "username": proxy_username, "password": proxy_password}

        browser: Browser = await p.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-dev-shm-usage", "--disable-blink-features=AutomationControlled"],
            proxy=proxy_settings
        )
        context = await browser.new_context(
            user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36',
            viewport={'width': 1920, 'height': 1080},
            locale='ko-KR',
            ignore_https_errors=True
        )
        page: Page = await context.new_page()
        base_url = "https://www.bdsplanet.com"

        try:
            await page.goto(f"{base_url}/main.ytp", wait_until="networkidle", timeout=90000)

            search_input = page.locator("input[placeholder*='주소'], input[placeholder*='검색']").first
            await search_input.wait_for(state="visible", timeout=10000)
            await search_input.fill(address)

            print("🔍 검색 실행 (Enter Press)")
            await search_input.press("Enter")

            # ✨ [수정된 부분] URL 변화를 단계적으로 관찰합니다.

            # 1. 검색 후 첫 페이지 로딩을 기다립니다 (중간 URL: ...tms 로 이동).
            print("⏳ 1단계: 중간 페이지 로딩을 기다립니다...")
            await page.wait_for_load_state("domcontentloaded", timeout=30000)
            intermediate_url = page.url
            print(f"✅ 1단계 완료. 중간 URL: {intermediate_url}")

            # 2. JS 리디렉션으로 인한 두 번째 페이지 로딩을 기다립니다 (최종 URL로 이동).
            print("⏳ 2단계: 최종 페이지 로딩을 기다립니다...")
            await page.wait_for_load_state("domcontentloaded", timeout=30000)
            final_url = page.url
            print(f"✅ 2단계 완료. 최종적으로 도착한 URL: {final_url}")

            # 3. 최종 도착한 URL이 우리가 기대한 패턴과 일치하는지 확인합니다.
            match = re.search(r"(/map/realprice_map/[^/]+/N/[ABC]/)([12])(/[^/]+\.ytp.*)", final_url)
            if match:
                print("👍 최종 URL이 예상 패턴과 일치합니다.")
                base_pattern, _, suffix = match.groups()
                sale_url = f"{base_url}{base_pattern}1{suffix}"
                rent_url = f"{base_url}{base_pattern}2{suffix}"

                await page.goto(sale_url, wait_until="domcontentloaded")
                sale_price = await extract_price(page)

                await page.goto(rent_url, wait_until="domcontentloaded")
                rent_price = await extract_price(page)

                return LowestPriceDto(address=address, salePrice=sale_price, rentPrice=rent_price, sourceUrl=sale_url)
            else:
                # 패턴이 일치하지 않으면 오류를 발생시켜 정확한 최종 URL을 확인합니다.
                raise TimeoutError(f"URL 패턴 분석 실패: 최종 URL이 예상과 다릅니다. 실제 최종 URL: {final_url}")

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