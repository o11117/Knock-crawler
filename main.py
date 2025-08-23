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
    # ✨ [수정] 각 단계에 로그를 추가합니다.
    print(f"🚀 '{address}' 주소에 대한 크롤링을 시작합니다.")

    async with async_playwright() as p:
        # --- 프록시 설정 부분은 그대로 유지 ---
        proxy_host = os.getenv("PROXY_HOST")
        proxy_port = os.getenv("PROXY_PORT")
        proxy_username = os.getenv("PROXY_USERNAME")
        proxy_password = os.getenv("PROXY_PASSWORD")

        proxy_settings = None
        if proxy_host and proxy_port:
            server = f"http://{proxy_host}:{proxy_port}"
            proxy_settings = {
                "server": server,
                "username": proxy_username,
                "password": proxy_password
            }
            print("✅ 프록시 설정이 감지되었습니다.")

        browser: Browser = await p.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-dev-shm-usage", "--disable-blink-features=AutomationControlled"],
            proxy=proxy_settings
        )
        print("✅ 브라우저 실행 완료.")

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
            await page.goto(f"{base_url}/main.ytp", wait_until="networkidle", timeout=90000)
            print("✅ 메인 페이지 접속 완료.")

            search_input = page.locator("input[placeholder*='주소'], input[placeholder*='검색']").first
            await search_input.wait_for(state="visible", timeout=10000)
            await search_input.fill(address)
            await search_input.press("Enter")
            print(f"✅ 주소 '{address}' 입력 및 검색 실행 완료.")

            expected_url_pattern = re.compile(r"/map/realprice_map/[^/]+/N/[ABC]/")
            end_time = time.time() + 30
            final_url = None
            print("🔍 검색 결과 페이지로 이동을 기다립니다 (최대 30초)...")
            while time.time() < end_time:
                current_url = page.url
                print(f"   - URL 확인 중... 현재 URL: {current_url}")  # URL 변경 과정을 추적
                if expected_url_pattern.search(current_url):
                    final_url = current_url
                    break
                await asyncio.sleep(1)  # 확인 간격을 1초로 늘려 로그가 너무 많이 쌓이는 것을 방지

            if not final_url:
                raise TimeoutError(f"30초 내에 검색 결과 페이지로 이동하지 못했습니다. 현재 URL: {page.url}")

            print(f"✅ 검색 결과 페이지로 이동 성공! 최종 URL: {final_url}")

            match = re.search(r"(/map/realprice_map/[^/]+/N/[ABC]/)([12])(/[^/]+\.ytp.*)", final_url)
            if match:
                base_pattern, _, suffix = match.groups()
                sale_url = f"{base_url}{base_pattern}1{suffix}"
                rent_url = f"{base_url}{base_pattern}2{suffix}"

                print("💰 매매가 추출 시도...")
                await page.goto(sale_url, wait_until="domcontentloaded")
                sale_price = await extract_price(page)
                print(f"   - 매매가: {sale_price}")

                print("💰 전세가 추출 시도...")
                await page.goto(rent_url, wait_until="domcontentloaded")
                rent_price = await extract_price(page)
                print(f"   - 전세가: {rent_price}")

                print("🏁 모든 가격 정보 추출 완료. 크롤링을 종료합니다.")
                return LowestPriceDto(address=address, salePrice=sale_price, rentPrice=rent_price, sourceUrl=sale_url)
            else:
                return LowestPriceDto(address=address, error=f"URL 패턴 분석 실패: {final_url}")

        except Exception as e:
            error_message = f"크롤링 오류 발생: {e}"
            print(f"🛑 {error_message}")  # 오류 발생 시 로그
            return LowestPriceDto(address=address, error=error_message)
        finally:
            await context.close()
            await browser.close()
            print("✅ 브라우저와 컨텍스트를 모두 닫았습니다.")


@app.get("/crawl", response_model=LowestPriceDto)
async def crawl_real_estate(address: str):
    if not address:
        raise HTTPException(status_code=400, detail="주소를 입력해주세요.")
    return await fetch_lowest_by_address(address)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)