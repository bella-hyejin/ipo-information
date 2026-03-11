"""
Google Calendar API 래퍼 모듈.

사전 준비:
  1. Google Cloud Console에서 Calendar API 활성화
  2. OAuth 2.0 클라이언트 ID(데스크톱 앱) 생성 후 credentials.json 저장
  3. 최초 실행 시 브라우저 인증 → token.json 자동 생성
"""

import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Optional

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from config import (
    GOOGLE_CALENDAR_ID,
    GOOGLE_CREDENTIALS_FILE,
    GOOGLE_SCOPES,
    GOOGLE_TOKEN_FILE,
    LISTING_EVENT_END_HOUR,
    LISTING_EVENT_END_MIN,
    LISTING_EVENT_START_HOUR,
    LISTING_EVENT_START_MIN,
    SUBSCRIPTION_EVENT_END_HOUR,
    SUBSCRIPTION_EVENT_END_MIN,
    SUBSCRIPTION_EVENT_START_HOUR,
    SUBSCRIPTION_EVENT_START_MIN,
)

logger = logging.getLogger(__name__)

KST = timezone(timedelta(hours=9))


# ── 인증 ────────────────────────────────────────────────────────────────────


def get_calendar_service():
    """
    Google Calendar API 서비스 객체를 반환한다.

    token.json이 있으면 재사용하고, 만료 시 자동 갱신한다.
    token.json이 없으면 브라우저 OAuth 인증을 진행하고 token.json을 생성한다.
    """
    creds: Optional[Credentials] = None

    if os.path.exists(GOOGLE_TOKEN_FILE):
        creds = Credentials.from_authorized_user_file(GOOGLE_TOKEN_FILE, GOOGLE_SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            logger.info("token.json 갱신 중...")
            creds.refresh(Request())
        else:
            if not os.path.exists(GOOGLE_CREDENTIALS_FILE):
                raise FileNotFoundError(
                    f"credentials.json을 찾을 수 없습니다: {GOOGLE_CREDENTIALS_FILE}\n"
                    "Google Cloud Console에서 OAuth 자격증명을 다운로드 후 저장하세요."
                )
            logger.info("브라우저 OAuth 인증 시작...")
            flow = InstalledAppFlow.from_client_secrets_file(
                GOOGLE_CREDENTIALS_FILE, GOOGLE_SCOPES
            )
            creds = flow.run_local_server(port=0)

        with open(GOOGLE_TOKEN_FILE, "w") as f:
            f.write(creds.to_json())
        logger.info("token.json 저장 완료")

    return build("calendar", "v3", credentials=creds)


# ── 날짜/시간 헬퍼 ───────────────────────────────────────────────────────────


def _to_iso_date(date_str: str) -> str:
    """
    크롤러 출력 날짜를 ISO 8601 형식으로 변환한다.

    Examples:
        "2026.03.12" → "2026-03-12"
        "2026/03/12" → "2026-03-12"
    """
    return date_str.replace(".", "-").replace("/", "-").strip()


def _make_datetime_str(date_iso: str, hour: int, minute: int) -> str:
    """
    날짜(ISO 형식)와 시/분으로 KST datetime 문자열을 생성한다.

    Returns:
        "2026-03-12T10:00:00+09:00" 형태 문자열.
    """
    year, month, day = (int(x) for x in date_iso.split("-"))
    dt = datetime(year, month, day, hour, minute, tzinfo=KST)
    return dt.isoformat()


# ── 이벤트 바디 빌더 ─────────────────────────────────────────────────────────


def build_subscription_event(item: dict) -> dict:
    """
    청약일정 데이터로 Google Calendar 이벤트 바디를 생성한다.

    PRD 포맷:
      제목: [청약] {종목명}
      날짜: 청약 마감일, 10:00~10:30 (KST)
      장소: 주간사
      설명: 공모가 / 청약일 / 경쟁률
      알림: 1일 전 (1440분)
    """
    종목명   = item.get("종목명", "")
    청약시작일 = item.get("청약시작일", "미정")
    청약마감일 = item.get("청약마감일", "미정")
    공모가   = item.get("공모가", "미정")
    경쟁률   = item.get("경쟁률", "미정")
    주간사   = item.get("주간사", "")

    # 마감일이 없으면 시작일을 대체 사용
    event_date_raw = 청약마감일 if 청약마감일 not in ("미정", "-", "") else 청약시작일
    event_date = _to_iso_date(event_date_raw) if event_date_raw not in ("미정", "-", "") else None

    if event_date is None:
        raise ValueError(f"청약 이벤트 날짜를 확정할 수 없습니다: {item}")

    return {
        "summary": f"[청약] {종목명}",
        "location": 주간사,
        "description": (
            f"공모가: {공모가}\n"
            f"청약일: {청약시작일}~{청약마감일}\n"
            f"경쟁률: {경쟁률}"
        ),
        "start": {
            "dateTime": _make_datetime_str(
                event_date, SUBSCRIPTION_EVENT_START_HOUR, SUBSCRIPTION_EVENT_START_MIN
            ),
            "timeZone": "Asia/Seoul",
        },
        "end": {
            "dateTime": _make_datetime_str(
                event_date, SUBSCRIPTION_EVENT_END_HOUR, SUBSCRIPTION_EVENT_END_MIN
            ),
            "timeZone": "Asia/Seoul",
        },
        "reminders": {
            "useDefault": False,
            "overrides": [{"method": "popup", "minutes": 1440}],  # 1일 전
        },
    }


def build_listing_event(item: dict) -> dict:
    """
    신규상장 데이터로 Google Calendar 이벤트 바디를 생성한다.

    PRD 포맷:
      제목: [상장] {종목명}
      날짜: 상장일, 09:00~09:30 (KST)
      설명: 공모가
      알림: 1시간 전 (60분)
    """
    종목명 = item.get("종목명", "")
    상장일 = item.get("상장일", "미정")
    공모가 = item.get("공모가", "미정")

    if 상장일 in ("미정", "-", ""):
        raise ValueError(f"상장 이벤트 날짜를 확정할 수 없습니다: {item}")

    event_date = _to_iso_date(상장일)

    return {
        "summary": f"[상장] {종목명}",
        "location": "",
        "description": f"공모가: {공모가}",
        "start": {
            "dateTime": _make_datetime_str(
                event_date, LISTING_EVENT_START_HOUR, LISTING_EVENT_START_MIN
            ),
            "timeZone": "Asia/Seoul",
        },
        "end": {
            "dateTime": _make_datetime_str(
                event_date, LISTING_EVENT_END_HOUR, LISTING_EVENT_END_MIN
            ),
            "timeZone": "Asia/Seoul",
        },
        "reminders": {
            "useDefault": False,
            "overrides": [{"method": "popup", "minutes": 60}],  # 1시간 전
        },
    }


# ── 이벤트 CRUD ─────────────────────────────────────────────────────────────


def create_event(service, body: dict) -> str:
    """
    Google Calendar에 이벤트를 생성하고 event_id를 반환한다.

    Raises:
        HttpError: API 오류 발생 시.
    """
    try:
        event = (
            service.events()
            .insert(calendarId=GOOGLE_CALENDAR_ID, body=body)
            .execute()
        )
        event_id = event.get("id", "")
        logger.info("이벤트 생성: %s (id=%s)", body.get("summary"), event_id)
        return event_id
    except HttpError as exc:
        logger.error("이벤트 생성 실패 (%s): %s", body.get("summary"), exc)
        raise


def update_event_description(service, event_id: str, new_description: str) -> None:
    """
    기존 이벤트의 description만 PATCH한다.
    공모가·경쟁률 등 변동 사항 반영에 사용한다.
    """
    try:
        service.events().patch(
            calendarId=GOOGLE_CALENDAR_ID,
            eventId=event_id,
            body={"description": new_description},
        ).execute()
        logger.info("이벤트 설명 업데이트 완료 (id=%s)", event_id)
    except HttpError as exc:
        logger.error("이벤트 설명 업데이트 실패 (id=%s): %s", event_id, exc)
        raise


def find_event_by_summary(service, summary: str) -> Optional[str]:
    """
    캘린더에서 제목으로 이벤트를 검색해 event_id를 반환한다.
    seen.json과의 교차 검증 또는 복구 목적으로 사용한다.

    Returns:
        event_id 문자열, 없으면 None.
    """
    try:
        result = (
            service.events()
            .list(
                calendarId=GOOGLE_CALENDAR_ID,
                q=summary,
                singleEvents=True,
                orderBy="startTime",
                maxResults=5,
            )
            .execute()
        )
        items = result.get("items", [])
        for event in items:
            if event.get("summary") == summary:
                return event.get("id")
        return None
    except HttpError as exc:
        logger.error("이벤트 검색 실패 (%s): %s", summary, exc)
        return None
