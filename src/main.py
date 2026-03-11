"""
공모주 캘린더 자동화 메인 오케스트레이터.

실행:
    python src/main.py

흐름:
  1. 38.co.kr 크롤링 (청약일정 + 신규상장)
  2. seen.json 로드 → 신규/변경 여부 판별
  3. Google Calendar 이벤트 생성 또는 description 업데이트
  4. seen.json 저장
"""

import logging
import sys

from calendar_service import (
    build_listing_event,
    build_subscription_event,
    create_event,
    find_event_by_summary,
    get_calendar_service,
    update_event_description,
)
from crawler import crawl_new_listings, crawl_subscription_schedule
from seen_manager import (
    compute_hash,
    get_record,
    load_seen,
    save_seen,
    upsert_record,
)
from slack_service import send_slack_alerts

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

# 청약 데이터 해시 대상 키
SUBSCRIPTION_HASH_KEYS = ["공모가", "경쟁률", "주간사"]
# 신규상장 데이터 해시 대상 키
LISTING_HASH_KEYS = ["공모가"]


def _build_subscription_description(item: dict) -> str:
    return (
        f"공모가: {item.get('공모가', '미정')}\n"
        f"청약일: {item.get('청약시작일', '미정')}~{item.get('청약마감일', '미정')}\n"
        f"경쟁률: {item.get('경쟁률', '미정')}"
    )


def _build_listing_description(item: dict) -> str:
    return f"공모가: {item.get('공모가', '미정')}"


def _process_subscription(service, seen: dict, item: dict) -> None:
    """청약일정 한 건을 처리한다 (신규 생성 또는 변경 업데이트)."""
    name = item["종목명"]
    data_hash = compute_hash(item, SUBSCRIPTION_HASH_KEYS)
    record = get_record(seen, "subscriptions", name)

    if record is None:
        # seen에 없음 → 캘린더에서 교차 검증
        existing_id = find_event_by_summary(service, f"[청약] {name}")
        if existing_id:
            logger.info("[청약] %s: 캘린더에 존재 → seen.json 복원", name)
            upsert_record(seen, "subscriptions", name, existing_id, data_hash)
            return

        # 완전 신규 → 이벤트 생성
        try:
            body = build_subscription_event(item)
            event_id = create_event(service, body)
            upsert_record(seen, "subscriptions", name, event_id, data_hash)
            logger.info("[청약] %s: 신규 이벤트 생성 완료", name)
        except (ValueError, Exception) as exc:
            logger.warning("[청약] %s: 이벤트 생성 실패 (%s)", name, exc)

    elif record["data_hash"] != data_hash:
        # 데이터 변경 → description 업데이트
        try:
            new_desc = _build_subscription_description(item)
            update_event_description(service, record["event_id"], new_desc)
            upsert_record(seen, "subscriptions", name, record["event_id"], data_hash)
            logger.info("[청약] %s: 이벤트 설명 업데이트 완료", name)
        except Exception as exc:
            logger.warning("[청약] %s: 이벤트 업데이트 실패 (%s)", name, exc)
    else:
        logger.debug("[청약] %s: 변경 없음, 스킵", name)


def _process_listing(service, seen: dict, item: dict) -> None:
    """신규상장 한 건을 처리한다 (신규 생성 또는 변경 업데이트)."""
    name = item["종목명"]
    data_hash = compute_hash(item, LISTING_HASH_KEYS)
    record = get_record(seen, "listings", name)

    if record is None:
        # seen에 없음 → 캘린더에서 교차 검증
        existing_id = find_event_by_summary(service, f"[상장] {name}")
        if existing_id:
            logger.info("[상장] %s: 캘린더에 존재 → seen.json 복원", name)
            upsert_record(seen, "listings", name, existing_id, data_hash)
            return

        # 완전 신규 → 이벤트 생성
        try:
            body = build_listing_event(item)
            event_id = create_event(service, body)
            upsert_record(seen, "listings", name, event_id, data_hash)
            logger.info("[상장] %s: 신규 이벤트 생성 완료", name)
        except (ValueError, Exception) as exc:
            logger.warning("[상장] %s: 이벤트 생성 실패 (%s)", name, exc)

    elif record["data_hash"] != data_hash:
        # 데이터 변경 → description 업데이트
        try:
            new_desc = _build_listing_description(item)
            update_event_description(service, record["event_id"], new_desc)
            upsert_record(seen, "listings", name, record["event_id"], data_hash)
            logger.info("[상장] %s: 이벤트 설명 업데이트 완료", name)
        except Exception as exc:
            logger.warning("[상장] %s: 이벤트 업데이트 실패 (%s)", name, exc)
    else:
        logger.debug("[상장] %s: 변경 없음, 스킵", name)


def run() -> None:
    """메인 실행 함수."""
    logger.info("=" * 60)
    logger.info("공모주 캘린더 자동화 시작")
    logger.info("=" * 60)

    # Google Calendar 서비스 초기화
    try:
        service = get_calendar_service()
    except FileNotFoundError as exc:
        logger.error(str(exc))
        sys.exit(1)

    seen = load_seen()

    # ── 청약일정 처리 ──────────────────────────────────────────────
    logger.info("── 청약일정 크롤링 시작 ──")
    subscription_items = crawl_subscription_schedule()
    logger.info("청약일정 %d건 수집", len(subscription_items))

    for item in subscription_items:
        try:
            _process_subscription(service, seen, item)
        except Exception as exc:
            logger.error("청약일정 처리 중 예외 (건너뜀): %s – %s", item.get("종목명"), exc)

    # ── 신규상장 처리 ──────────────────────────────────────────────
    logger.info("── 신규상장 크롤링 시작 ──")
    listing_items = crawl_new_listings()
    logger.info("신규상장 %d건 수집", len(listing_items))

    for item in listing_items:
        try:
            _process_listing(service, seen, item)
        except Exception as exc:
            logger.error("신규상장 처리 중 예외 (건너뜀): %s – %s", item.get("종목명"), exc)

    save_seen(seen)

    # ── Slack 알림 발송 ────────────────────────────────────────────
    logger.info("── Slack 알림 확인 중 ──")
    send_slack_alerts(subscription_items, listing_items)

    logger.info("=" * 60)
    logger.info("완료: 청약 %d건 / 신규상장 %d건 처리", len(subscription_items), len(listing_items))
    logger.info("=" * 60)


if __name__ == "__main__":
    run()
