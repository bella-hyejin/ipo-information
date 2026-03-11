import os

from dotenv import load_dotenv

load_dotenv()

BASE_URL = "https://www.38.co.kr"

# 공모주 청약일정 직접 URL
# 출처: 38.co.kr 청약일정 탭 onmousedown="ipogo('/html/fund/index.htm?o=k')"
SUBSCRIPTION_URL = "https://www.38.co.kr/html/fund/index.htm?o=k"

# 신규상장 직접 URL
# 출처: 38.co.kr 신규상장 탭 onmousedown="ipogo('/html/fund/index.htm?o=nw')"
NEW_LISTING_URL = "https://www.38.co.kr/html/fund/index.htm?o=nw"

# Selenium 설정
SELENIUM_HEADLESS = True
SELENIUM_TIMEOUT = 10          # WebDriverWait 최대 대기 시간(초)
PAGE_LOAD_TIMEOUT = 30         # driver.set_page_load_timeout 값(초)

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/122.0.0.0 Safari/537.36"
)

# 청약일정 테이블 CSS 셀렉터 (사용자 제공)
SUBSCRIPTION_TABLE_SELECTOR = (
    "body > table:nth-child(9) > tbody > tr > td > "
    "table:nth-child(2) > tbody > tr > td:nth-child(1) > "
    "table:nth-child(11) > tbody > tr:nth-child(2) > td > table"
)

# ── 청약일정 실제 컬럼 (사이트 헤더 기준) ──────────────────────────────────
# 실제 헤더: 종목명 / 공모주일정 / 확정공모가 / 희망공모가 / 청약경쟁률 / 주간사 / 분석
SUBSCRIPTION_COLUMNS = {
    "종목명": 0,
    "공모주일정": 1,   # "2026.03.11~03.12" 형태 → 시작일/마감일 파싱 필요
    "확정공모가": 2,
    "희망공모가": 3,
    "청약경쟁률": 4,
    "주간사": 5,
}

# 신규상장 테이블 CSS 셀렉터 (사용자 제공)
NEW_LISTING_TABLE_SELECTOR = (
    "body > table:nth-child(9) > tbody > tr > td > "
    "table:nth-child(2) > tbody > tr > td:nth-child(1) > "
    "table:nth-child(12) > tbody > tr:nth-child(2) > td > table"
)

# ── 신규상장 실제 컬럼 (사이트 헤더 기준) ───────────────────────────────────
# 실제 헤더: 기업명 / 신규상장일 / 현재가(원) / 전일비(%) / 공모가(원) / 공모가대비등락률(%) / ...
NEW_LISTING_COLUMNS = {
    "기업명": 0,
    "신규상장일": 1,
    "현재가(원)": 2,
    "전일비(%)": 3,
    "공모가(원)": 4,
}

# ── Google Calendar ─────────────────────────────────────────────────────────
GOOGLE_CREDENTIALS_FILE = os.getenv("GOOGLE_CREDENTIALS_FILE", "credentials.json")
GOOGLE_TOKEN_FILE = os.getenv("GOOGLE_TOKEN_FILE", "token.json")
GOOGLE_CALENDAR_ID = os.getenv("GOOGLE_CALENDAR_ID", "primary")
GOOGLE_SCOPES = ["https://www.googleapis.com/auth/calendar"]

# ── seen.json ───────────────────────────────────────────────────────────────
SEEN_FILE = os.getenv("SEEN_FILE", "seen.json")

# ── 이벤트 시간 (KST, UTC+9) ────────────────────────────────────────────────
SUBSCRIPTION_EVENT_START_HOUR = 10   # 청약 이벤트 10:00
SUBSCRIPTION_EVENT_START_MIN  = 0
SUBSCRIPTION_EVENT_END_HOUR   = 10
SUBSCRIPTION_EVENT_END_MIN    = 30
LISTING_EVENT_START_HOUR      = 9    # 상장 이벤트 09:00
LISTING_EVENT_START_MIN       = 0
LISTING_EVENT_END_HOUR        = 9
LISTING_EVENT_END_MIN         = 30

# ── Slack ────────────────────────────────────────────────────────────────────
SLACK_BOT_TOKEN  = os.getenv("SLACK_BOT_TOKEN", "")
SLACK_CHANNEL_ID = os.getenv("SLACK_CHANNEL_ID", "#ipo-alerts")
