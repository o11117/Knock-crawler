# main.py (Pydantic V2 호환 최종 버전)
import asyncio
import os
import re
import time
from fastapi import FastAPI, HTTPException, BackgroundTasks
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
    async with async_playwright() as p:
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
            print("🔍 메인 페이지 접속 시도...")
            await page.goto(f"{base_url}/main.ytp", wait_until="domcontentloaded", timeout=60000)
            print("✅ 메인 페이지 접속 완료.")

            try:
                ad_pop_selector = ".pop.adPop"
                await page.wait_for_selector(ad_pop_selector, state="visible", timeout=7000)
                await page.evaluate(f"document.querySelector('{ad_pop_selector}').remove();")
                print("✅ 광고 팝업을 강제로 제거했습니다.")
            except TimeoutError:
                print("ℹ️ 광고 팝업이 감지되지 않았습니다.")

            search_input = page.locator("input[placeholder*='주소'], input[placeholder*='검색']").first
            await search_input.wait_for(state="visible", timeout=10000)

            await search_input.fill(address)
            print(f"✅ 주소 '{address}' 입력 완료.")

            autocomplete_selector = ".ui-autocomplete .ui-menu-item"
            await page.wait_for_selector(autocomplete_selector, timeout=10000)
            print("✅ 자동완성 목록 표시됨.")

            await page.locator(autocomplete_selector).first.click()
            print("✅ 자동완성 첫 번째 항목 클릭 완료.")

            final_url_pattern = re.compile(r"/map/realprice_map/[^/]+/N/[ABC]/")
            await page.wait_for_url(final_url_pattern, timeout=60000)
            final_url = page.url
            print(f"✅ 최종 URL 도착: {final_url}")

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


async def run_crawling_and_log_result(address: str):
    print(f"🚀 '{address}'에 대한 백그라운드 크롤링 작업을 시작합니다.")
    result = await fetch_lowest_by_address(address)
    print("--- 최종 크롤링 결과 ---")

    # ✨ [수정] Pydantic V2에 맞는 model_dump_json() 함수를 사용합니다.
    print(result.model_dump_json(indent=2))

    print("--- 작업 완료 ---")


@app.get("/crawl")
async def crawl_real_estate(address: str, background_tasks: BackgroundTasks):
    if not address:
        raise HTTPException(status_code=400, detail="주소를 입력해주세요.")

    background_tasks.add_task(run_crawling_and_log_result, address)

    return {"message": "크롤링 작업이 시작되었습니다. 잠시 후 서버 로그를 확인하세요."}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)