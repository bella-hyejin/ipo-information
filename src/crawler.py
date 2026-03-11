"""
38.co.kr 공모주 청약일정 및 신규상장 정보 크롤러.

실행:
    python src/crawler.py
"""

import json
import logging
import time
from typing import Optional

from bs4 import BeautifulSoup
from selenium import webdriver
from selenium.common.exceptions import TimeoutException, WebDriverException
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait
from webdriver_manager.chrome import ChromeDriverManager

from config import (
    NEW_LISTING_COLUMNS,
    NEW_LISTING_TABLE_SELECTOR,
    NEW_LISTING_URL,
    PAGE_LOAD_TIMEOUT,
    SELENIUM_HEADLESS,
    SELENIUM_TIMEOUT,
    SUBSCRIPTION_COLUMNS,
    SUBSCRIPTION_TABLE_SELECTOR,
    SUBSCRIPTION_URL,
    USER_AGENT,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)


# ── 드라이버 ────────────────────────────────────────────────────────────────


def get_driver() -> webdriver.Chrome:
    """headless Chrome 드라이버를 생성하여 반환한다."""
    options = webdriver.ChromeOptions()
    if SELENIUM_HEADLESS:
        options.add_argument("--headless=new")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    options.add_argument("--window-size=1920,1080")
    options.add_argument(f"user-agent={USER_AGENT}")

    driver = webdriver.Chrome(
        service=Service(ChromeDriverManager().install()),
        options=options,
    )
    driver.set_page_load_timeout(PAGE_LOAD_TIMEOUT)
    return driver


def fetch_page_source(
    url: str,
    wait_selector: Optional[str] = None,
    retries: int = 3,
) -> Optional[str]:
    """
    Selenium으로 페이지를 로드하고 page_source를 반환한다.

    Args:
        url: 로드할 URL.
        wait_selector: 로딩 완료를 판단할 CSS 셀렉터 (None이면 단순 대기).
        retries: 네트워크 오류 시 최대 재시도 횟수.

    Returns:
        HTML 문자열, 실패 시 None.
    """
    for attempt in range(1, retries + 1):
        driver = None
        try:
            driver = get_driver()
            logger.info("페이지 로드 중 (시도 %d/%d): %s", attempt, retries, url)
            driver.get(url)

            if wait_selector:
                WebDriverWait(driver, SELENIUM_TIMEOUT).until(
                    EC.presence_of_element_located((By.CSS_SELECTOR, wait_selector))
                )
            else:
                time.sleep(2)

            return driver.page_source

        except TimeoutException:
            logger.warning("페이지 로드 타임아웃 (시도 %d/%d): %s", attempt, retries, url)
        except WebDriverException as exc:
            logger.error("WebDriverException (시도 %d/%d): %s", attempt, retries, exc)
        finally:
            if driver:
                driver.quit()

        if attempt < retries:
            wait = 2 ** attempt
            logger.info("%.0f초 후 재시도합니다.", wait)
            time.sleep(wait)

    logger.error("모든 재시도 실패: %s", url)
    return None


# ── 파싱 헬퍼 ───────────────────────────────────────────────────────────────


def _safe_text(tag) -> str:
    """태그에서 공백 제거 텍스트를 추출한다. 태그가 None이면 '미정'을 반환한다."""
    if tag is None:
        return "미정"
    text = tag.get_text(strip=True)
    return text if text else "미정"


def _detect_column_map(header_row) -> dict[str, int]:
    """
    테이블 헤더 행(tr)에서 컬럼명 → 인덱스 매핑을 자동으로 생성한다.
    헤더 감지 실패 시 config의 SUBSCRIPTION_COLUMNS fallback을 사용한다.
    """
    cells = header_row.find_all(["th", "td"])
    col_map: dict[str, int] = {}
    for idx, cell in enumerate(cells):
        text = cell.get_text(strip=True)
        col_map[text] = idx
    return col_map if col_map else SUBSCRIPTION_COLUMNS


# ── 청약일정 파싱 ───────────────────────────────────────────────────────────


def _parse_subscription_dates(date_range: str) -> tuple[str, str]:
    """
    "2026.03.11~03.12" 형태의 청약일정 문자열을 시작일/마감일로 분리한다.

    Returns:
        (청약시작일, 청약마감일) 튜플. 파싱 실패 시 ("미정", "미정").
    """
    if not date_range or date_range == "미정":
        return ("미정", "미정")
    try:
        parts = date_range.split("~")
        start = parts[0].strip()
        if len(parts) < 2:
            return (start, "미정")
        end_raw = parts[1].strip()
        # 마감일이 "03.12" 형태면 시작일의 연도를 붙인다.
        if len(end_raw) <= 5 and "." in end_raw:
            year = start.split(".")[0]
            end_raw = f"{year}.{end_raw}"
        return (start, end_raw)
    except Exception:
        return (date_range, "미정")


def parse_subscription_schedule(html: str) -> list[dict]:
    """
    청약일정 페이지 HTML을 파싱하여 종목 리스트를 반환한다.

    실제 테이블 컬럼: 종목명 / 공모주일정 / 확정공모가 / 희망공모가 / 청약경쟁률 / 주간사

    Returns:
        [{"종목명": str, "청약시작일": str, "청약마감일": str,
          "공모가": str, "경쟁률": str, "주간사": str}, ...]
    """
    soup = BeautifulSoup(html, "lxml")
    results: list[dict] = []

    try:
        table = soup.select_one(SUBSCRIPTION_TABLE_SELECTOR)
        if table is None:
            logger.warning(
                "청약일정 테이블을 찾을 수 없습니다. 셀렉터를 확인하세요: %s",
                SUBSCRIPTION_TABLE_SELECTOR,
            )
            return results

        rows = table.find_all("tr")
        if not rows:
            logger.warning("청약일정 테이블에 행이 없습니다.")
            return results

        col_map = _detect_column_map(rows[0])
        logger.info("감지된 청약일정 컬럼: %s", col_map)

        for row in rows[1:]:
            cells = row.find_all("td")
            if len(cells) < 2:
                continue

            try:
                def get_cell(key: str) -> str:
                    idx = col_map.get(key, SUBSCRIPTION_COLUMNS.get(key))
                    if idx is None or idx >= len(cells):
                        return "미정"
                    return _safe_text(cells[idx])

                종목명 = get_cell("종목명")
                if 종목명 == "미정":
                    continue

                # 청약일정: "2026.03.11~03.12" 형태를 시작일/마감일로 분리
                date_range = get_cell("공모주일정")
                청약시작일, 청약마감일 = _parse_subscription_dates(date_range)

                # 공모가: 확정공모가가 있으면 우선, 없으면 희망공모가 사용
                확정공모가 = get_cell("확정공모가")
                희망공모가 = get_cell("희망공모가")
                공모가 = 확정공모가 if 확정공모가 not in ("-", "미정") else 희망공모가

                item = {
                    "종목명": 종목명,
                    "청약시작일": 청약시작일,
                    "청약마감일": 청약마감일,
                    "공모가": 공모가,
                    "경쟁률": get_cell("청약경쟁률"),
                    "주간사": get_cell("주간사"),
                }
                results.append(item)

            except Exception as exc:
                logger.warning("청약일정 행 파싱 중 오류 (건너뜀): %s", exc)
                continue

    except Exception as exc:
        logger.error("청약일정 파싱 중 예외 발생: %s", exc)

    logger.info("청약일정 파싱 완료: %d건", len(results))
    return results


# ── 신규상장 파싱 ───────────────────────────────────────────────────────────


def parse_new_listings(html: str) -> list[dict]:
    """
    신규상장 페이지 HTML을 파싱하여 종목 리스트를 반환한다.

    실제 테이블 컬럼: 기업명 / 신규상장일 / 현재가(원) / 전일비(%) / 공모가(원) / ...

    Returns:
        [{"종목명": str, "상장일": str, "공모가": str}, ...]
    """
    soup = BeautifulSoup(html, "lxml")
    results: list[dict] = []

    try:
        table = soup.select_one(NEW_LISTING_TABLE_SELECTOR)
        if table is None:
            logger.warning(
                "신규상장 테이블을 찾을 수 없습니다. 셀렉터를 확인하세요: %s",
                NEW_LISTING_TABLE_SELECTOR,
            )
            return results

        rows = table.find_all("tr")
        if not rows:
            logger.warning("신규상장 테이블에 행이 없습니다.")
            return results

        col_map = _detect_column_map(rows[0])
        logger.info("감지된 신규상장 컬럼: %s", col_map)

        for row in rows[1:]:
            cells = row.find_all("td")
            if len(cells) < 2:
                continue

            try:
                def get_cell(key: str) -> str:
                    idx = col_map.get(key, NEW_LISTING_COLUMNS.get(key))
                    if idx is None or idx >= len(cells):
                        return "미정"
                    return _safe_text(cells[idx])

                # 사이트 헤더가 "기업명"이므로 "기업명" 우선, fallback으로 "종목명"
                종목명 = get_cell("기업명") or get_cell("종목명")
                if 종목명 == "미정":
                    continue

                item = {
                    "종목명": 종목명,
                    "상장일": get_cell("신규상장일"),
                    "공모가": get_cell("공모가(원)"),
                }
                results.append(item)

            except Exception as exc:
                logger.warning("신규상장 행 파싱 중 오류 (건너뜀): %s", exc)
                continue

    except Exception as exc:
        logger.error("신규상장 파싱 중 예외 발생: %s", exc)

    logger.info("신규상장 파싱 완료: %d건", len(results))
    return results


# ── 퍼블릭 크롤링 함수 ──────────────────────────────────────────────────────


def crawl_subscription_schedule() -> list[dict]:
    """
    38.co.kr 공모주 청약일정 페이지를 크롤링하여 종목 리스트를 반환한다.
    """
    html = fetch_page_source(
        SUBSCRIPTION_URL,
        wait_selector=SUBSCRIPTION_TABLE_SELECTOR,
    )
    if html is None:
        logger.error("청약일정 페이지 로드 실패.")
        return []
    return parse_subscription_schedule(html)


def crawl_new_listings() -> list[dict]:
    """
    38.co.kr 신규상장 페이지를 크롤링하여 종목 리스트를 반환한다.
    """
    html = fetch_page_source(
        NEW_LISTING_URL,
        wait_selector=NEW_LISTING_TABLE_SELECTOR,
    )
    if html is None:
        logger.error("신규상장 페이지 로드 실패.")
        return []
    return parse_new_listings(html)


# ── 진입점 ──────────────────────────────────────────────────────────────────


if __name__ == "__main__":
    print("\n" + "=" * 60)
    print("  공모주 청약일정 크롤링")
    print("=" * 60)
    subscription_data = crawl_subscription_schedule()
    print(json.dumps(subscription_data, ensure_ascii=False, indent=2))

    print("\n" + "=" * 60)
    print("  신규상장 크롤링")
    print("=" * 60)
    new_listing_data = crawl_new_listings()
    print(json.dumps(new_listing_data, ensure_ascii=False, indent=2))

    print(f"\n총 청약일정: {len(subscription_data)}건 / 신규상장: {len(new_listing_data)}건")
