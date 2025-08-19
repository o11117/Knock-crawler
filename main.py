# main.py (안정성 강화 최종 버전)
import asyncio
import re
import time
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from playwright.async_api import async_playwright, Page, Browser, TimeoutError
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

# ✨ [수정] 가격 추출 로직 안정성 강화
async def extract_price(page: Page) -> Union[int, None]:
    try:
        # 가격 정보 영역이 나타날 때까지 최대 7초 대기
        await page.wait_for_selector(".price-info-area", timeout=7000)

        # "매물 최저가" 라벨이 있는지 확인
        label = page.locator("*:has-text('매물 최저가')").first
        if await label.count() > 0:
            price_area = label.locator("..").locator(".price-info-area .price-area .txt")
            if await price_area.count() > 0:
                price_text = await price_area.first.text_content()
                if price_text and ('억' in price_text or '만' in price_text):
                    return to_won(price_text.strip())

        # "매물 최저가"가 없다면, 일반 가격 탐색
        price_elements = await page.locator(".price-info-area .price-area .txt").all()
        for el in price_elements:
            price_text = await el.text_content()
            if price_text and ('억' in price_text or '만' in price_text):
                price = to_won(price_text.strip())
                if price > 0:
                    return price
    except TimeoutError:
        print("가격 정보 영역을 시간 내에 찾지 못했습니다.")
        return None
    except Exception as e:
        print(f"가격 추출 중 오류: {e}")
    return None

# ✨ [수정] 전체 크롤링 로직 안정성 대폭 강화
async def fetch_lowest_by_address(address: str) -> LowestPriceDto:
    async with async_playwright() as p:
        browser: Browser = await p.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox",
                "--disable-dev-shm-usage",
                "--disable-blink-features=AutomationControlled" # 자동화 탐지 우회 강화
            ]
        )
        context = await browser.new_context(
            user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36',
            viewport={'width': 1920, 'height': 1080},
            locale='ko-KR',
            extra_http_headers={ # 헤더 추가
                'Accept-Language': 'ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7'
            }
        )
        page: Page = await context.new_page()
        base_url = "https://www.bdsplanet.com"

        try:
            # 1. 사이트 접속 (재시도 로직 추가)
            for i in range(2): # 최대 2회 시도
                try:
                    await page.goto(f"{base_url}/main.ytp", wait_until="domcontentloaded", timeout=15000)
                    break # 성공 시 루프 탈출
                except TimeoutError as e:
                    if i == 1: # 마지막 시도도 실패하면 에러 발생
                        raise e
                    print(f"페이지 로드 시간 초과, 재시도합니다... ({i+1}/2)")
                    await asyncio.sleep(1)

            # 2. 검색 실행
            search_input = page.locator("input[placeholder*='주소'], input[placeholder*='검색']").first
            await search_input.wait_for(state="visible", timeout=10000)
            await search_input.fill(address)
            await search_input.press("Enter")

            # 3. ✨ [핵심] URL 변경 폴링(Polling) 루프
            # 검색 후 상세 페이지로 넘어갈 때까지 최대 15초간 반복 확인
            expected_url_pattern = re.compile(r"/map/realprice_map/[^/]+/N/[ABC]/")
            end_time = time.time() + 15 # 최대 15초 대기
            final_url = None

            while time.time() < end_time:
                current_url = page.url
                if expected_url_pattern.search(current_url):
                    final_url = current_url
                    break
                await asyncio.sleep(0.5) # 0.5초 간격으로 확인

            if not final_url:
                raise TimeoutError(f"15초 내에 검색 결과 페이지로 이동하지 못했습니다. 현재 URL: {page.url}")

            # 4. URL 분석 및 가격 추출
            match = re.search(r"(/map/realprice_map/[^/]+/N/[ABC]/)([12])(/[^/]+\.ytp.*)", final_url)

            if match:
                base_pattern, _, suffix = match.groups()
                sale_url = f"{base_url}{base_pattern}1{suffix}"
                rent_url = f"{base_url}{base_pattern}2{suffix}"

                # 매매가 추출
                await page.goto(sale_url, wait_until="domcontentloaded")
                sale_price = await extract_price(page)

                # 전세가 추출
                await page.goto(rent_url, wait_until="domcontentloaded")
                rent_price = await extract_price(page)

                return LowestPriceDto(address=address, salePrice=sale_price, rentPrice=rent_price, sourceUrl=sale_url)
            else:
                return LowestPriceDto(address=address, error=f"URL 패턴 분석 실패: {final_url}")

        except TimeoutError as e:
            # 디버깅을 위해 실패 시 스크린샷 저장
            await page.screenshot(path="debug_screenshot_timeout.png")
            return LowestPriceDto(address=address, error=f"작업 시간 초과: {e}")
        except Exception as e:
            await page.screenshot(path="debug_screenshot_error.png")
            return LowestPriceDto(address=address, error=f"크롤링 오류: {e}")
        finally:
            await context.close()
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