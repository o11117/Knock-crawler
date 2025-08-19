# main.py (팝업 처리 기능이 포함된 최종 버전)
import asyncio
import re
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from playwright.async_api import async_playwright, Page, Browser, TimeoutError as PlaywrightTimeoutError
from playwright_stealth import stealth_async
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

async def handle_popups(page: Page):
    """페이지에 접속했을 때 나타날 수 있는 팝업이나 오버레이를 확인하고 닫습니다."""
    print("[로그] 팝업/오버레이 확인 중...")
    try:
        # 일반적인 팝업 닫기 버튼 선택자 목록
        close_button_selectors = [
            "button:has-text('닫기')",
            "button[class*='close']",
            "a[class*='close']",
            "img[alt*='close']",
            "div[class*='popup'] button[class*='close']",
            ".btn_close"  # bdsplanet에서 사용하는 팝업 닫기 버튼 클래스
        ]

        for selector in close_button_selectors:
            close_button = page.locator(selector).first
            # 팝업이 나타날 때까지 최대 2초만 기다림
            if await close_button.is_visible(timeout=2000):
                print(f"[로그] 팝업 닫기 버튼 '{selector}' 찾음. 클릭 시도...")
                await close_button.click(timeout=5000)
                await page.wait_for_timeout(500)  # 닫히는 애니메이션 대기
                print("[로그] 팝업 닫기 완료.")
                return  # 팝업을 하나 닫았으면 함수 종료

        print("[로그] 추가로 감지된 팝업 없음.")
    except PlaywrightTimeoutError:
        # 타임아웃은 팝업이 없다는 의미이므로 정상 처리
        print("[로그] 감지된 팝업 없음 (타임아웃).")
    except Exception as e:
        # 다른 오류는 로그만 남기고 무시하여 크롤링이 중단되지 않도록 함
        print(f"[경고] 팝업 처리 중 예외 발생 (무시하고 계속 진행): {e}")


async def extract_price(page: Page) -> Union[int, None]:
    # ... 가격 추출 로직은 이전과 동일 ...
    try:
        print("[로그] 가격 추출 시작...")
        await page.wait_for_load_state('networkidle', timeout=10000)
        selectors = [
            "*:has-text('매물 최저가') >> .. >> .price-info-area .price-area .txt",
            ".price-info-area .price-area .txt",
        ]
        for selector in selectors:
            elements = await page.locator(selector).all()
            for el in elements:
                if await el.is_visible(timeout=1000):
                    price_text = await el.text_content()
                    if price_text and ('억' in price_text or '만' in price_text):
                        price = to_won(price_text.strip())
                        if price > 0:
                            print(f"[로그] 가격 추출 성공: {price}")
                            return price
        print("[로그] 페이지에서 가격 정보를 찾지 못했습니다.")
    except Exception as e:
        print(f"[오류] 가격 추출 중 오류 발생: {e}")
    return None


async def fetch_lowest_by_address(address: str) -> LowestPriceDto:
    print(f"\n--- [로그] 새로운 크롤링 요청 시작 (대상: bdsplanet.com, 스텔스 모드) ---")
    print(f"[로그] 요청 주소: {address}")
    async with async_playwright() as p:
        browser: Browser = await p.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-dev-shm-usage", "--disable-gpu"]
        )
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/114.0.0.0 Safari/537.36"
        )
        page: Page = await context.new_page()
        await stealth_async(page)

        base_url = "https://www.bdsplanet.com"
        page.set_default_timeout(45000)

        try:
            print("[로그] 1. 사이트 접속 시도...")
            await page.goto(base_url, wait_until="load", timeout=30000)
            print("[로그] 1. 사이트 접속 성공")

            # --- ▼▼▼▼▼ 핵심 수정 부분 ▼▼▼▼▼ ---
            # 페이지 접속 직후 팝업 처리 로직 호출
            await handle_popups(page)
            # --- ▲▲▲▲▲ 핵심 수정 부분 ▲▲▲▲▲ ---

            print("[로그] 2. 검색창 탐색 및 주소 입력...")
            search_input = page.locator("input#searchInput").first
            await search_input.wait_for(state="visible", timeout=15000)
            await search_input.type(address, delay=120)
            print("[로그] 2. 주소 입력 완료")

            print("[로그] 3. 드롭다운 목록 대기 및 첫번째 항목 클릭 시도...")
            first_result_selector = "ul.d_list > li.list_item > a"
            first_result = page.locator(first_result_selector).first
            await first_result.wait_for(state="visible", timeout=10000)

            await asyncio.gather(
                page.wait_for_load_state("networkidle", timeout=20000),
                first_result.click()
            )
            print("[로그] 3. 드롭다운 첫번째 항목 클릭 및 페이지 이동 성공")

            current_url = page.url
            print(f"[로그] 4. 현재 URL: {current_url}")
            match = re.search(r"(/map/realprice_map/[^/]+/N/[ABC]/)([12])(/[^/]+\\.ytp)", current_url)

            if match:
                print("[로그] 4. URL 패턴 분석 성공")
                base_pattern, _, suffix = match.groups()

                sale_url = f"{base_url}{base_pattern}1{suffix}"
                print(f"[로그] 4a. 매매 정보 페이지로 이동: {sale_url}")
                await page.goto(sale_url, wait_until="domcontentloaded")
                sale_price = await extract_price(page)

                rent_url = f"{base_url}{base_pattern}2{suffix}"
                print(f"[로그] 4b. 전세 정보 페이지로 이동: {rent_url}")
                await page.goto(rent_url, wait_until="domcontentloaded")
                rent_price = await extract_price(page)

                print("[로그] 크롤링 최종 성공")
                return LowestPriceDto(address=address, salePrice=sale_price, rentPrice=rent_price, sourceUrl=sale_url)
            else:
                print("[오류] 4. URL 패턴 분석 실패")
                return LowestPriceDto(address=address, error=f"URL 패턴 분석 실패: {current_url}")

        except Exception as e:
            error_message = str(e).splitlines()[0]
            print(f"[오류] 크롤링 전체 과정에서 오류 발생: {error_message}")
            return LowestPriceDto(address=address, error=f"크롤링 오류: {error_message}")
        finally:
            await browser.close()
            print("[로그] 브라우저 종료 및 자원 정리 완료")


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