# main.py (환경변수 적용 최종 버전)
import asyncio
import os  # ✨ os 모듈 추가
import re
import time
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from playwright.async_api import async_playwright, Page, Browser, TimeoutError
from typing import Union
from money_parser import to_won
import traceback

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

        # ✨ [수정] 환경변수에서 프록시 정보를 읽어옵니다.
        proxy_host = os.getenv("PROXY_HOST")
        proxy_port = os.getenv("PROXY_PORT")
        proxy_username = os.getenv("PROXY_USERNAME")
        proxy_password = os.getenv("PROXY_PASSWORD")

        proxy_settings = None
        # 환경변수가 설정된 경우에만 프록시 설정을 구성합니다.
        if proxy_host and proxy_port:
            server = f"http://{proxy_host}:{proxy_port}"
            proxy_settings = {
                "server": server,
                "username": proxy_username,
                "password": proxy_password
            }

        browser: Browser = await p.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox",
                "--disable-dev-shm-usage",
                "--disable-blink-features=AutomationControlled"
            ],
            proxy=proxy_settings
        )
        context = await browser.new_context(
            user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36',
            viewport={'width': 1920, 'height': 1080},
            locale='ko-KR',
            ignore_https_errors=True
        )
        page: Page = await context.new_page()

        # ✨ [핵심 수정 1] 요청하신 URL에서 크롤링을 시작합니다.
        start_url = "https://www.bdsplanet.com/map/realprice_map.ytp?ubt_mode=tms"

        try:
            # ✨ [핵심 추가] IP 주소 확인 로직
            print("=====================================")
            print(">>> 현재 IP 주소를 확인합니다...")
            await page.goto("https://httpbin.org/ip", wait_until="domcontentloaded")
            ip_info = await page.locator("body").text_content()
            print(f">>> 감지된 IP 주소: {ip_info.strip()}")
            print("=====================================")

            await page.goto(start_url, wait_until="networkidle", timeout=90000)

            # ✨ [핵심 수정 2] 지도 페이지의 검색창을 찾아 주소를 입력하고 'Enter'를 누릅니다.
            search_input_selector = 'input[name="search_keyword"]'
            await page.wait_for_selector(search_input_selector, timeout=10000)
            search_input = page.locator(search_input_selector)
            await search_input.fill(address)
            await search_input.press("Enter")

            # ✨ [핵심 수정 3] URL이 바뀌기를 30초 동안 안정적으로 기다립니다.
            expected_url_pattern = re.compile(r"/map/realprice_map/[^/]+/")
            await page.wait_for_url(expected_url_pattern, timeout=30000)
            final_url = page.url

            match = re.search(r"(/map/realprice_map/.*/)([12])(/.*)", final_url)

            if match:
                base_pattern, _, suffix = match.groups()

                # ✨ [핵심 수정 4] URL 조합 오류를 방지하기 위해 전체 도메인을 직접 사용합니다.
                base_domain = "https://www.bdsplanet.com"
                sale_url = f"{base_domain}{base_pattern}1{suffix}"
                rent_url = f"{base_domain}{base_pattern}2{suffix}"

                await page.goto(sale_url, wait_until="domcontentloaded")
                sale_price = await extract_price(page)

                await page.goto(rent_url, wait_until="domcontentloaded")
                rent_price = await extract_price(page)

                return LowestPriceDto(address=address, salePrice=sale_price, rentPrice=rent_price, sourceUrl=sale_url)
            else:
                return LowestPriceDto(address=address, error=f"URL 패턴 분석 실패: {final_url}")

        except Exception as e:

            # ✨ [핵심 수정] 오류 발생 시 상세한 Traceback을 콘솔에 출력합니다.

            print("=====================================")

            print(f"!!! CRITICAL ERROR IN CRAWLER: {e}")

            traceback.print_exc()  # 오류의 전체 경로를 출력

            print("=====================================")

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