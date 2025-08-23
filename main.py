# main.py
import asyncio
import re
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from playwright.async_api import async_playwright, Page, Browser, TimeoutError
from typing import Union, Optional


# R-TECH 사이트의 가격 포맷(예: '59,000')을 원 단위 정수로 변환하는 함수
def parse_price_in_manwon(price_str: Optional[str]) -> Optional[int]:
    """
    '59,000'과 같이 만원 단위로 된 가격 문자열을 원 단위 정수로 변환합니다.
    공백, 쉼표를 제거하고 10000을 곱합니다.
    """
    if not price_str or not price_str.strip():
        return None
    try:
        # 공백 및 쉼표 제거 후 정수로 변환
        cleaned_price = int(price_str.replace(',', '').strip())
        # 만원 단위를 원 단위로 변환
        return cleaned_price * 10000
    except (ValueError, TypeError):
        return None


app = FastAPI()


# 반환될 데이터 구조(DTO) 정의
class RtechPriceDto(BaseModel):
    address: str
    saleLowerAvg: Union[int, None] = None
    saleUpperAvg: Union[int, None] = None
    rentLowerAvg: Union[int, None] = None
    rentUpperAvg: Union[int, None] = None
    sourceUrl: Union[str, None] = None
    error: Union[str, None] = None


async def extract_prices_from_popup(page: Page) -> dict:
    """새로운 팝업 창에서 매매가와 전세가의 상한/하한 평균가를 추출합니다."""

    # ✨ [수정된 부분] 대기 조건을 더 강화합니다.
    # 테이블의 행(tr)이 아니라, 가격 정보가 담기는 파란색 텍스트의 셀(td.table_txt_blue)이
    # 실제로 렌더링될 때까지 최대 20초간 기다립니다.
    try:
        await page.wait_for_selector("#areaList > tr > td.table_txt_blue", timeout=20000)
    except TimeoutError:
        print("가격 정보 테이블이 시간 내에 로드되지 않았습니다. 해당 주소의 시세 정보가 없을 수 있습니다.")
        return {}  # 타임아웃 발생 시 빈 딕셔너리 반환

    # 첫 번째 면적(row)을 기준으로 가격을 추출합니다.
    base_row_selector = "#areaList > tr:first-child"
    sale_lower_selector = f"{base_row_selector} > td:nth-child(3)"
    sale_upper_selector = f"{base_row_selector} > td:nth-child(4)"
    rent_lower_selector = f"{base_row_selector} > td:nth-child(5)"
    rent_upper_selector = f"{base_row_selector} > td:nth-child(6)"

    try:
        # 각 선택자에 해당하는 요소의 텍스트를 가져옵니다.
        sale_lower_text = await page.locator(sale_lower_selector).text_content()
        sale_upper_text = await page.locator(sale_upper_selector).text_content()
        rent_lower_text = await page.locator(rent_lower_selector).text_content()
        rent_upper_text = await page.locator(rent_upper_selector).text_content()

        # 가져온 텍스트를 원 단위 숫자로 변환합니다.
        return {
            "saleLowerAvg": parse_price_in_manwon(sale_lower_text),
            "saleUpperAvg": parse_price_in_manwon(sale_upper_text),
            "rentLowerAvg": parse_price_in_manwon(rent_lower_text),
            "rentUpperAvg": parse_price_in_manwon(rent_upper_text),
        }
    except Exception as e:
        print(f"가격 추출 중 오류 발생: {e}")
        return {}


# 크롤링 로직을 담당하는 메인 함수
async def fetch_prices_from_rtech(address: str) -> RtechPriceDto:
    async with async_playwright() as p:
        browser: Browser = await p.chromium.launch(
            headless=True,  # 실제 운영 시에는 True로 변경하는 것이 좋습니다.
            args=["--no-sandbox", "--disable-dev-shm-usage"]
        )
        context = await browser.new_context(
            user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36',
            locale='ko-KR'
        )
        page: Page = await context.new_page()
        base_url = "https://rtech.or.kr/main/mapSearch.do"

        try:
            # 1. 사이트 접속
            await page.goto(base_url, wait_until="networkidle", timeout=30000)

            # 2. '빠른검색' 창에 주소 입력 (ID: searchInput)
            search_input_selector = "#searchInput"
            await page.wait_for_selector(search_input_selector, timeout=10000)
            await page.locator(search_input_selector).fill(address)

            # 3. 3초 대기 후 드롭다운 첫번째 항목 클릭
            await page.wait_for_timeout(3000)
            first_item_selector = "#quickSearchResult > li:first-child > a"
            await page.wait_for_selector(first_item_selector, timeout=10000)

            # ✨ [수정된 부분] 여러 개의 요소를 찾더라도 첫 번째 요소를 클릭하도록 .first 추가
            await page.locator(first_item_selector).first.click()

            # 지도 위 정보창이 뜨는 것을 잠시 대기
            await page.wait_for_timeout(1000)

            # 4. '더보기' 버튼 클릭 및 새 창(팝업) 처리
            async with context.expect_page() as new_page_info:
                more_button_selector = ".map_pop_info_bottom_btn:has-text('더보기')"
                await page.wait_for_selector(more_button_selector, timeout=10000)
                await page.locator(more_button_selector).click()

            popup_page = await new_page_info.value
            await popup_page.wait_for_load_state("domcontentloaded")

            # 5. 새 창에서 가격 정보 추출
            prices = await extract_prices_from_popup(popup_page)

            return RtechPriceDto(
                address=address,
                saleLowerAvg=prices.get("saleLowerAvg"),
                saleUpperAvg=prices.get("saleUpperAvg"),
                rentLowerAvg=prices.get("rentLowerAvg"),
                rentUpperAvg=prices.get("rentUpperAvg"),
                sourceUrl=popup_page.url
            )

        except Exception as e:
            return RtechPriceDto(address=address, error=f"크롤링 오류 발생: {e}")
        finally:
            await context.close()
            await browser.close()


# API 엔드포인트
@app.get("/crawl", response_model=RtechPriceDto)
async def crawl_rtech_prices(address: str):
    if not address:
        raise HTTPException(status_code=400, detail="주소를 입력해주세요.")
    return await fetch_prices_from_rtech(address)


if __name__ == "__main__":
    import uvicorn

    # 터미널에서 uvicorn main:app --reload --host 0.0.0.0 --port 8000 명령어로 실행
    uvicorn.run(app, host="0.0.0.0", port=8000)