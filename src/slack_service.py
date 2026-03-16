"""
Slack 알림 발송 모듈.

RUN_MODE별 발송 조건:
  - morning (08:00 KST): 신규/변경 청약·상장 종목 알림 + 상장일==오늘 알림
  - open    (10:00 KST): 청약시작일==오늘인 종목 알림
  - close   (18:00 KST): 청약마감일<=오늘이면서 데이터가 변경된 종목 알림

사전 준비:
  1. api.slack.com/apps 에서 앱 생성 후 chat:write 권한 추가
  2. Bot User OAuth Token을 .env의 SLACK_BOT_TOKEN에 저장
  3. 알림 채널에 봇 초대: /invite @봇이름
  4. SLACK_CHANNEL_ID에 채널명(#ipo-alerts) 또는 채널 ID(C...) 저장
"""

import logging
from datetime import date

from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError

from config import SLACK_BOT_TOKEN, SLACK_CHANNEL_ID

logger = logging.getLogger(__name__)


# ── 클라이언트 ────────────────────────────────────────────────────────────────


def get_slack_client() -> WebClient:
    """Slack WebClient를 반환한다."""
    if not SLACK_BOT_TOKEN:
        raise ValueError(
            "SLACK_BOT_TOKEN이 설정되지 않았습니다. .env 파일을 확인하세요."
        )
    return WebClient(token=SLACK_BOT_TOKEN)


# ── 날짜 파싱 헬퍼 ────────────────────────────────────────────────────────────


def _parse_date(date_str: str) -> date | None:
    """
    크롤러 출력 날짜 문자열을 date 객체로 변환한다.

    지원 형식:
        "2026.03.12" → date(2026, 3, 12)
        "2026/03/12" → date(2026, 3, 12)
        "2026-03-12" → date(2026, 3, 12)
    """
    if not date_str or date_str in ("미정", "-", ""):
        return None
    normalized = date_str.replace(".", "-").replace("/", "-").strip()
    try:
        parts = normalized.split("-")
        return date(int(parts[0]), int(parts[1]), int(parts[2]))
    except (ValueError, IndexError):
        logger.warning("날짜 파싱 실패: %r", date_str)
        return None


# ── 메시지 포맷 ───────────────────────────────────────────────────────────────


def format_subscription_message(item: dict) -> str:
    """
    청약 알림 Slack 메시지를 생성한다.

    PRD 포맷:
        🔔 *[청약] {종목명}*
        • 공모가: {공모가}
        • 주관사: {주간사}
        • 청약일: {청약시작일}~{청약마감일}
        • 경쟁률: {경쟁률}
    """
    return (
        f"🔔 *[청약] {item.get('종목명', '')}*\n"
        f"• 공모가: {item.get('공모가', '미정')}\n"
        f"• 주관사: {item.get('주간사', '미정')}\n"
        f"• 청약일: {item.get('청약시작일', '미정')}~{item.get('청약마감일', '미정')}\n"
        f"• 경쟁률: {item.get('경쟁률', '미정')}"
    )


def format_listing_message(item: dict) -> str:
    """
    상장 알림 Slack 메시지를 생성한다.

    PRD 포맷:
        🎉 *[상장] {종목명}*
        • 공모가: {공모가}
        • 상장일: {상장일}
    """
    return (
        f"🎉 *[상장] {item.get('종목명', '')}*\n"
        f"• 공모가: {item.get('공모가', '미정')}\n"
        f"• 상장일: {item.get('상장일', '미정')}"
    )


# ── 발송 ──────────────────────────────────────────────────────────────────────


def send_message(client: WebClient, text: str) -> bool:
    """
    Slack 채널에 메시지를 발송한다.

    Returns:
        발송 성공 여부.
    """
    try:
        client.chat_postMessage(channel=SLACK_CHANNEL_ID, text=text)
        logger.info("Slack 메시지 발송 성공: %.40s...", text.replace("\n", " "))
        return True
    except SlackApiError as exc:
        logger.error("Slack 메시지 발송 실패: %s", exc.response["error"])
        return False


# ── 클라이언트 초기화 헬퍼 ───────────────────────────────────────────────────


def _init_client() -> WebClient | None:
    """토큰 검증 후 WebClient를 반환한다. 미설정 시 None을 반환한다."""
    if not SLACK_BOT_TOKEN:
        logger.warning("SLACK_BOT_TOKEN 미설정 → Slack 알림 건너뜀")
        return None
    try:
        return get_slack_client()
    except ValueError as exc:
        logger.error(str(exc))
        return None


# ── 모드별 알림 함수 ──────────────────────────────────────────────────────────


def send_morning_alerts(
    subscription_items: list[dict],
    listing_items: list[dict],
    updated_subs: list[dict],
    updated_listings: list[dict],
) -> None:
    """
    [morning 모드 / 08:00 KST] 기능 3 + 4 알림 발송.

    - 기능 4: 신규·변경된 청약·상장 종목 알림
    - 기능 3: 상장일==오늘인 종목 알림 (기능 4와 중복 발송 방지)

    Args:
        subscription_items: 전체 청약 크롤링 결과.
        listing_items: 전체 상장 크롤링 결과.
        updated_subs: 신규 또는 변경된 청약 종목 목록.
        updated_listings: 신규 또는 변경된 상장 종목 목록.
    """
    client = _init_client()
    if client is None:
        return

    today = date.today()
    sent = 0

    # ── 기능 4: 신규·변경 청약 종목 ───────────────────────────────────────
    for item in updated_subs:
        text = format_subscription_message(item)
        if send_message(client, text):
            sent += 1
            logger.info("[morning/청약 업데이트] %s", item.get("종목명"))

    # ── 기능 4: 신규·변경 상장 종목 ───────────────────────────────────────
    updated_listing_names = {item["종목명"] for item in updated_listings}
    for item in updated_listings:
        text = format_listing_message(item)
        if send_message(client, text):
            sent += 1
            logger.info("[morning/상장 업데이트] %s", item.get("종목명"))

    # ── 기능 3: 상장일==오늘 (기능 4에서 이미 보낸 종목 제외) ───────────
    for item in listing_items:
        if item["종목명"] in updated_listing_names:
            continue
        상장일 = _parse_date(item.get("상장일", ""))
        if 상장일 != today:
            continue
        text = format_listing_message(item)
        if send_message(client, text):
            sent += 1
            logger.info("[morning/상장 당일] %s (상장일: %s)", item.get("종목명"), 상장일)

    logger.info("Slack 알림 발송 완료 (morning): 총 %d건", sent)


def send_open_alerts(subscription_items: list[dict]) -> None:
    """
    [open 모드 / 10:00 KST] 기능 1 알림 발송.

    청약시작일==오늘인 종목을 Slack으로 전달한다.

    Args:
        subscription_items: 전체 청약 크롤링 결과.
    """
    client = _init_client()
    if client is None:
        return

    today = date.today()
    sent = 0

    for item in subscription_items:
        시작일 = _parse_date(item.get("청약시작일", ""))
        if 시작일 != today:
            continue
        text = format_subscription_message(item)
        if send_message(client, text):
            sent += 1
            logger.info("[open/청약시작] %s (시작일: %s)", item.get("종목명"), 시작일)

    logger.info("Slack 알림 발송 완료 (open): 총 %d건", sent)


def send_close_update_alerts(changed_subs: list[dict]) -> None:
    """
    [close 모드 / 18:00 KST] 기능 2 알림 발송.

    청약마감일<=오늘이면서 데이터가 변경된 종목(경쟁률 확정 등)을 Slack으로 전달한다.

    Args:
        changed_subs: main.py에서 hash 변경이 감지된 청약 종목 목록.
    """
    client = _init_client()
    if client is None:
        return

    today = date.today()
    sent = 0

    for item in changed_subs:
        마감일 = _parse_date(item.get("청약마감일", ""))
        if 마감일 is None or 마감일 > today:
            continue
        text = format_subscription_message(item)
        if send_message(client, text):
            sent += 1
            logger.info(
                "[close/마감후업데이트] %s (마감일: %s)", item.get("종목명"), 마감일
            )

    logger.info("Slack 알림 발송 완료 (close): 총 %d건", sent)
