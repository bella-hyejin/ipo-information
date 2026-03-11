"""
Slack 알림 발송 모듈.

발송 조건:
  - 청약 이벤트: 청약 마감일이 내일(오늘 + 1일)인 종목
  - 상장 이벤트: 상장일이 오늘인 종목 (매일 08:00 실행 시 상장 1시간 전 효과)

사전 준비:
  1. api.slack.com/apps 에서 앱 생성 후 chat:write 권한 추가
  2. Bot User OAuth Token을 .env의 SLACK_BOT_TOKEN에 저장
  3. 알림 채널에 봇 초대: /invite @봇이름
  4. SLACK_CHANNEL_ID에 채널명(#ipo-alerts) 또는 채널 ID(C...) 저장
"""

import json
import logging
import time
from datetime import date, timedelta

from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError

from config import SLACK_BOT_TOKEN, SLACK_CHANNEL_ID

# #region agent log
_DEBUG_LOG = "/Users/tia.lee/Documents/dev-cursor/.cursor/debug-0ca51e.log"


def _dbg(msg: str, data: dict, hypothesis: str) -> None:
    entry = {
        "sessionId": "0ca51e", "runId": "post-fix", "hypothesisId": hypothesis,
        "location": "slack_service.py", "message": msg, "data": data,
        "timestamp": int(time.time() * 1000),
    }
    with open(_DEBUG_LOG, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")
# #endregion

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
        # #region agent log
        _dbg("메시지 발송 성공", {"preview": text[:60]}, "E")
        # #endregion
        return True
    except SlackApiError as exc:
        logger.error("Slack 메시지 발송 실패: %s", exc.response["error"])
        # #region agent log
        _dbg("메시지 발송 실패", {"error": exc.response.get("error", "unknown")}, "E")
        # #endregion
        return False


# ── 메인 알림 함수 ────────────────────────────────────────────────────────────


def send_slack_alerts(
    subscription_items: list[dict],
    listing_items: list[dict],
) -> None:
    """
    크롤 결과를 날짜 조건으로 필터링하여 Slack 알림을 발송한다.

    Args:
        subscription_items: crawl_subscription_schedule() 반환값.
        listing_items: crawl_new_listings() 반환값.
    """
    # #region agent log
    _dbg("send_slack_alerts 진입", {
        "token_set": bool(SLACK_BOT_TOKEN),
        "token_prefix": SLACK_BOT_TOKEN[:10] if SLACK_BOT_TOKEN else "",
        "channel": SLACK_CHANNEL_ID,
    }, "C")
    # #endregion

    if not SLACK_BOT_TOKEN:
        logger.warning("SLACK_BOT_TOKEN 미설정 → Slack 알림 건너뜀")
        # #region agent log
        _dbg("SLACK_BOT_TOKEN 없음 → 스킵", {}, "C")
        # #endregion
        return

    try:
        client = get_slack_client()
    except ValueError as exc:
        logger.error(str(exc))
        return

    today = date.today()
    tomorrow = today + timedelta(days=1)

    # #region agent log
    _dbg("날짜 기준 설정", {"today": str(today), "tomorrow": str(tomorrow)}, "D")
    sub_deadlines = [item.get("청약마감일", "") for item in subscription_items]
    list_dates = [item.get("상장일", "") for item in listing_items]
    _dbg("크롤 데이터 날짜 목록", {
        "청약마감일_목록": sub_deadlines[:10],
        "상장일_목록": list_dates[:10],
    }, "D")
    # #endregion

    sent = 0

    # ── 청약 알림: 마감일 == 내일 ──────────────────────────────────────────
    for item in subscription_items:
        마감일 = _parse_date(item.get("청약마감일", ""))
        if 마감일 != tomorrow:
            continue
        text = format_subscription_message(item)
        if send_message(client, text):
            sent += 1
            logger.info("[청약 알림] %s (마감일: %s)", item.get("종목명"), 마감일)

    # ── 상장 알림: 상장일 == 오늘 ──────────────────────────────────────────
    for item in listing_items:
        상장일 = _parse_date(item.get("상장일", ""))
        if 상장일 != today:
            continue
        text = format_listing_message(item)
        if send_message(client, text):
            sent += 1
            logger.info("[상장 알림] %s (상장일: %s)", item.get("종목명"), 상장일)

    # #region agent log
    _dbg("Slack 알림 완료", {"sent": sent}, "E")
    # #endregion
    logger.info("Slack 알림 발송 완료: 총 %d건", sent)
