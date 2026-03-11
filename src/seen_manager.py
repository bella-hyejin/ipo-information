"""
seen.json 기반 종목 처리 상태 관리 모듈.

seen.json 구조:
{
  "subscriptions": {
    "종목명": {
      "event_id": "google_calendar_event_id",
      "data_hash": "md5(공모가+경쟁률+주간사)",
      "last_updated": "2026-03-10"
    }
  },
  "listings": {
    "종목명": {
      "event_id": "google_calendar_event_id",
      "data_hash": "md5(공모가)",
      "last_updated": "2026-03-10"
    }
  }
}
"""

import hashlib
import json
import logging
from datetime import date
from pathlib import Path
from typing import Optional

from config import SEEN_FILE

logger = logging.getLogger(__name__)

_EMPTY_SEEN: dict = {"subscriptions": {}, "listings": {}}


def load_seen() -> dict:
    """seen.json을 읽어 반환한다. 파일이 없으면 빈 구조를 반환한다."""
    path = Path(SEEN_FILE)
    if not path.exists():
        logger.info("seen.json 없음 → 빈 구조로 초기화")
        return {"subscriptions": {}, "listings": {}}
    try:
        with path.open(encoding="utf-8") as f:
            data = json.load(f)
        # 필수 키 보정
        data.setdefault("subscriptions", {})
        data.setdefault("listings", {})
        return data
    except (json.JSONDecodeError, OSError) as exc:
        logger.error("seen.json 읽기 실패 (%s) → 빈 구조로 초기화", exc)
        return {"subscriptions": {}, "listings": {}}


def save_seen(data: dict) -> None:
    """seen.json에 데이터를 저장한다."""
    path = Path(SEEN_FILE)
    try:
        with path.open("w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        logger.info("seen.json 저장 완료: %s", path.resolve())
    except OSError as exc:
        logger.error("seen.json 저장 실패: %s", exc)


def compute_hash(item: dict, keys: list[str]) -> str:
    """
    item 딕셔너리에서 지정된 키들의 값을 이어 붙여 MD5 해시를 생성한다.
    데이터 변경 여부를 비교하는 데 사용한다.
    """
    raw = "|".join(str(item.get(k, "")) for k in keys)
    return hashlib.md5(raw.encode("utf-8")).hexdigest()


def get_record(seen: dict, category: str, name: str) -> Optional[dict]:
    """
    seen 딕셔너리에서 특정 카테고리/종목명 레코드를 조회한다.

    Args:
        seen: load_seen() 반환값.
        category: "subscriptions" 또는 "listings".
        name: 종목명.

    Returns:
        레코드 dict 또는 None (미등록 시).
    """
    return seen.get(category, {}).get(name)


def upsert_record(
    seen: dict,
    category: str,
    name: str,
    event_id: str,
    data_hash: str,
) -> None:
    """
    seen 딕셔너리에 레코드를 추가하거나 업데이트한다.
    save_seen()은 별도로 호출해야 한다.

    Args:
        seen: load_seen() 반환값 (in-place 수정).
        category: "subscriptions" 또는 "listings".
        name: 종목명.
        event_id: Google Calendar 이벤트 ID.
        data_hash: compute_hash() 결과.
    """
    seen.setdefault(category, {})[name] = {
        "event_id": event_id,
        "data_hash": data_hash,
        "last_updated": date.today().isoformat(),
    }
