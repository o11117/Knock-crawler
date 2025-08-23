# main.py (초기 로딩 안정화 최종 버전)
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
    try:
        await page.wait_for_selector(".price-info-area", timeout=10000)
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
    start_time = time.time()
    print(f"🚀 '{address}' 크롤링 시작...")

    async with async_playwright() as p:
        proxy_host, proxy_port, proxy_username, proxy_password = (
            os.getenv("PROXY_HOST"),
            os.getenv("PROXY_PORT"),
            os.getenv("PROXY_USERNAME"),
            os.getenv("PROXY_PASSWORD"),
        )
        proxy_settings = None
        if proxy_host and proxy_port:
            server = f"http://{proxy_host}:{proxy_port}"
            proxy_settings = {"server": server, "username": proxy_username, "password": proxy_password}

        browser: Browser = await p.chromium.launch(headless=True, args=["--no-sandbox"], proxy=proxy_settings)
        context = await browser.new_context(
            user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36',
            ignore_https_errors=True
        )
        page: Page = await context.new_page()
        base_url = "https://www.bdsplanet.com"

        try:
            print(f"[{time.time() - start_time:.2f}s] 🔍 메인 페이지 접속 시도...")
            # ✨ [수정 1] 페이지 로딩이 완료될 때까지 기다리지 않고, 일단 접속만 시도합니다.
            await page.goto(f"{base_url}/main.ytp", timeout=60000)
            print(f"[{time.time() - start_time:.2f}s] ✅ 페이지 기본 로딩 완료.")

            # ✨ [수정 2] 페이지의 핵심 요소인 '검색창'이 나타날 때까지 기다립니다.
            search_input_selector = "input[placeholder*='주소'], input[placeholder*='검색']"
            search_input = page.locator(search_input_selector).first
            await search_input.wait_for(state="visible", timeout=60000)
            print(f"[{time.time() - start_time:.2f}s] ✅ 검색창 표시 확인.")

            await asyncio.sleep(1)  # 페이지 스크립트가 안정화될 시간을 줍니다.

            try:
                ad_pop_selector = ".pop.adPop"
                await page.wait_for_selector(ad_pop_selector, state="visible", timeout=7000)
                await page.evaluate(f"document.querySelector('{ad_pop_selector}').remove();")
                print(f"[{time.time() - start_time:.2f}s] ✅ 광고 팝업 제거 완료.")
            except TimeoutError:
                print(f"[{time.time() - start_time:.2f}s] ℹ️ 광고 팝업 감지되지 않음.")

            await search_input.fill(address)

            autocomplete_selector = ".ui-autocomplete .ui-menu-item"
            await page.wait_for_selector(autocomplete_selector, timeout=10000)
            await page.locator(autocomplete_selector).first.click()
            print(f"[{time.time() - start_time:.2f}s] ✅ 검색 실행 완료.")

            final_url_pattern = re.compile(r"/map/realprice_map/[^/]+/N/[ABC]/")
            await page.wait_for_url(final_url_pattern, timeout=60000)
            final_url = page.url
            print(f"[{time.time() - start_time:.2f}s] ✅ 최종 URL 도착: {final_url}")

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