from __future__ import annotations

import csv
import hashlib
import json
import mimetypes
import os
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from dotenv import load_dotenv
from google import genai
from google.genai import types
from pydantic import BaseModel, Field, ValidationError, field_validator

load_dotenv()

IMAGE_DIR = Path(os.getenv("IMAGE_DIR", "data/images"))
OUTPUT_DIR = Path(os.getenv("OUTPUT_DIR", "outputs"))
MODEL_NAME = os.getenv("GEMINI_MODEL", "gemini-3.5-flash-lite")
MAX_OUTPUT_TOKENS = int(os.getenv("MAX_OUTPUT_TOKENS", "1800"))

SOURCE_TYPES = {
    "instagram_feed": "인스타그램 피드",
    "instagram_reel": "인스타그램 릴스",
    "instagram_story": "인스타그램 스토리",
    "youtube_longform": "유튜브 롱폼",
    "youtube_shorts": "유튜브 쇼츠",
    "naver_blog": "네이버 블로그",
    "naver_map": "네이버 지도",
    "naver_shopping": "네이버 쇼핑",
    "naver_search": "네이버 검색",
    "shopping_site": "쇼핑 사이트",
    "web_article": "웹 기사·정보 페이지",
    "email_or_notice": "이메일·공지",
    "app_screen": "앱 화면",
    "gallery_or_photo": "갤러리·일반 사진",
    "other": "기타",
    "unknown": "알 수 없음",
}

SourceType = Literal[
    "instagram_feed",
    "instagram_reel",
    "instagram_story",
    "youtube_longform",
    "youtube_shorts",
    "naver_blog",
    "naver_map",
    "naver_shopping",
    "naver_search",
    "shopping_site",
    "web_article",
    "email_or_notice",
    "app_screen",
    "gallery_or_photo",
    "other",
    "unknown",
]

BUCKETS = {
    "food.cook": "요리해보고 싶은 것",
    "food.eat": "먹어보고 싶은 것",
    "food.visit": "맛집·카페 가보기",
    "place.visit": "방문하고 싶은 곳",
    "travel.plan": "여행 계획 세우기",
    "product.buy": "사고 싶은 것",
    "product.compare": "비교해보고 싶은 제품",
    "style.inspire": "스타일·코디 참고",
    "activity.try": "한번 해보고 싶은 활동",
    "activity.hobby": "취미로 시작하고 싶은 것",
    "learning.study": "공부·탐구해보고 싶은 것",
    "book.read": "읽고 싶은 책",
    "book.buy": "사고 싶은 책",
    "content.watch": "보고 싶은 콘텐츠",
    "content.listen": "듣고 싶은 콘텐츠",
    "event.attend": "참여하고 싶은 행사",
    "task.apply": "신청할 것",
    "task.reserve": "예약할 것",
    "task.check": "확인할 것",
    "reference.howto": "사용법·문제 해결 정보",
    "reference.save": "나중에 참고할 정보",
    "gift.idea": "선물 아이디어",
    "thought.save": "기억하고 싶은 생각·문장",
    "wellness.routine": "건강·루틴으로 실천할 것",
}

BucketType = Literal[
    "food.cook",
    "food.eat",
    "food.visit",
    "place.visit",
    "travel.plan",
    "product.buy",
    "product.compare",
    "style.inspire",
    "activity.try",
    "activity.hobby",
    "learning.study",
    "book.read",
    "book.buy",
    "content.watch",
    "content.listen",
    "event.attend",
    "task.apply",
    "task.reserve",
    "task.check",
    "reference.howto",
    "reference.save",
    "gift.idea",
    "thought.save",
    "wellness.routine",
]

CANDIDATE_COLUMNS = ["선택", "제목", "버킷 ID", "대상", "이유"]


def _clean_text(value: object, limit: int) -> str:
    text = " ".join(str(value or "").split())
    return text[:limit].strip()


def _clean_list(value: object, limit: int, item_limit: int = 80) -> list[str]:
    if not isinstance(value, list):
        return []
    output: list[str] = []
    seen: set[str] = set()
    for item in value:
        text = _clean_text(item, item_limit)
        key = text.casefold()
        if text and key not in seen:
            output.append(text)
            seen.add(key)
        if len(output) >= limit:
            break
    return output


class ActionCandidate(BaseModel):
    title: str = Field(description="사용자에게 보여줄 구체적인 행동 제목.")
    subject: str = Field(description="행동의 핵심 대상. 예: 토마토 요리 모음, 독립서점 지도, 여름 하객룩")
    bucket_id: BucketType
    reason: str = Field(description="왜 이 후보를 제안했는지 한 문장 설명.")

    @field_validator("title", mode="before")
    @classmethod
    def clean_title(cls, value: object) -> str:
        return _clean_text(value, 100)

    @field_validator("subject", mode="before")
    @classmethod
    def clean_subject(cls, value: object) -> str:
        return _clean_text(value, 80)

    @field_validator("reason", mode="before")
    @classmethod
    def clean_reason(cls, value: object) -> str:
        return _clean_text(value, 120)


class AnalysisResult(BaseModel):
    summary: str = Field(description="스크린샷의 중심 내용을 한 문장으로 요약.")
    key_text: str = Field(description="전체 OCR이 아니라 검색에 필요한 핵심 문구 요약.")
    source_type: SourceType
    source_name: str | None = Field(default=None, description="화면에 보이는 계정명·채널명·사이트명. 없으면 null.")
    content_dates: list[str] = Field(default_factory=list, description="콘텐츠 안에 보이는 날짜·기간·마감일 원문만 저장.")
    objects: list[str] = Field(default_factory=list)
    colors: list[str] = Field(default_factory=list)
    places: list[str] = Field(default_factory=list)
    activities: list[str] = Field(default_factory=list)
    keywords: list[str] = Field(default_factory=list)
    action_candidates: list[ActionCandidate] = Field(
        min_length=3,
        max_length=3,
        description="서로 다른 행동 후보 정확히 3개.",
    )

    @field_validator("summary", mode="before")
    @classmethod
    def clean_summary(cls, value: object) -> str:
        return _clean_text(value, 200)

    @field_validator("key_text", mode="before")
    @classmethod
    def clean_key_text(cls, value: object) -> str:
        return _clean_text(value, 700)

    @field_validator("source_name", mode="before")
    @classmethod
    def clean_source_name(cls, value: object) -> str | None:
        text = _clean_text(value, 80)
        return text or None

    @field_validator("content_dates", mode="before")
    @classmethod
    def clean_content_dates(cls, value: object) -> list[str]:
        return _clean_list(value, 5, 100)

    @field_validator("objects", mode="before")
    @classmethod
    def clean_objects(cls, value: object) -> list[str]:
        return _clean_list(value, 8)

    @field_validator("colors", mode="before")
    @classmethod
    def clean_colors(cls, value: object) -> list[str]:
        return _clean_list(value, 5)

    @field_validator("places", mode="before")
    @classmethod
    def clean_places(cls, value: object) -> list[str]:
        return _clean_list(value, 5)

    @field_validator("activities", mode="before")
    @classmethod
    def clean_activities(cls, value: object) -> list[str]:
        return _clean_list(value, 5)

    @field_validator("keywords", mode="before")
    @classmethod
    def clean_keywords(cls, value: object) -> list[str]:
        return _clean_list(value, 10)

    @field_validator("action_candidates", mode="before")
    @classmethod
    def limit_candidates(cls, value: object) -> list:
        return value[:3] if isinstance(value, list) else []


@dataclass
class TokenUsage:
    prompt_tokens: int = 0
    output_tokens: int = 0
    thought_tokens: int = 0
    total_tokens: int = 0
    calls: int = 0

    def add(self, response: object) -> None:
        metadata = getattr(response, "usage_metadata", None)
        self.calls += 1
        if metadata is None:
            return
        self.prompt_tokens += int(getattr(metadata, "prompt_token_count", 0) or 0)
        self.output_tokens += int(getattr(metadata, "candidates_token_count", 0) or 0)
        self.thought_tokens += int(getattr(metadata, "thoughts_token_count", 0) or 0)
        self.total_tokens += int(getattr(metadata, "total_token_count", 0) or 0)


@dataclass
class AnalysisRun:
    result: AnalysisResult
    status: str
    usage: TokenUsage
    model: str


MAIN_PROMPT = f"""
당신은 모바일 스크린샷을 개인의 실행 가능한 관심 목록으로 바꾸는 분석기입니다.
이미지를 보고 최종 JSON만 반환하세요. 분석 과정이나 작업 메모는 출력하지 마세요.

반드시 지킬 규칙:
1. 화면에서 직접 확인되는 사실만 메타데이터로 저장합니다.
2. 알 수 없는 출처명은 null, 출처 유형은 unknown으로 둡니다.
3. key_text는 전체 OCR이 아니라 검색에 필요한 핵심 문구만 700자 이하로 작성합니다.
4. content_dates에는 콘텐츠 안에 표시된 날짜·기간·마감일 원문만 최대 5개 기록합니다.
   휴대전화 상태바 시각, 스크린샷 저장일, 게시물이 '3일 전'이라고 표시된 상대 시각은 제외합니다.
5. 날짜를 year/month/day로 변환하거나 화면에 없는 연도를 추정하지 않습니다.
6. evidence와 confidence는 만들지 않습니다.
7. 행동 후보는 정확히 3개 제안합니다.
8. 세 후보는 서로 중복되지 않아야 하며, 가능하면 서로 다른 관점의 행동이어야 합니다.
9. 화면의 특정 요소를 반영하는 후보도 좋지만, 화면 전체를 아우르는 공통 주제 기반 후보도 허용됩니다.
   예: 토마토 요리 여러 개가 보이면 '토마토 요리 모음 저장하고 하나 골라 만들어보기' 같은 포괄 후보 가능.
   예: 책 리스트가 많으면 개별 책만 고르지 말고 '여성주의 책 읽기 리스트로 저장하기'처럼 공통 주제 후보 가능.
10. 메인 콘텐츠뿐 아니라 화면에서 명확히 보이는 부가 요소도 독립적 관심사라면 후보가 될 수 있습니다.
    단, 광고성 요소는 사용자가 실제 관심 가질 가능성이 높을 때만 후보로 포함합니다.
11. 모든 자연어는 한국어로 작성합니다.

행동 후보 작성 규칙:
- 정확히 3개만 작성합니다.
- 서로 다른 대상-행동 조합이어야 합니다.
- 다음 관점 중 적절한 것을 활용하세요: 구매, 비교, 방문, 여행계획, 시청·읽기, 공부, 직접 만들어보기,
  취미로 확장, 신청·예약, 문제 해결, 참고 저장, 건강 루틴, 선물 아이디어, 스타일 참고, 생각 저장.
- 후보가 모두 개별 요소만 다루거나 모두 포괄적이면 안 됩니다. 화면에 따라 적절히 균형 있게 구성하세요.
- 화면에 명확한 여러 아이템이 있을 때는 1개 이상은 공통 주제 기반 후보를 고려하세요.
- 근거가 빈약한 환상적 행동은 만들지 마세요.

출처 유형:
{json.dumps(SOURCE_TYPES, ensure_ascii=False, indent=2)}

버킷:
{json.dumps(BUCKETS, ensure_ascii=False, indent=2)}
"""

RETRY_PROMPT = MAIN_PROMPT + """
이전 응답은 형식 오류가 있었습니다. 이번에는 더 짧고 간결하게 작성하세요.
summary는 120자 이하, key_text는 500자 이하,
각 태그 배열은 핵심 항목만 유지하고 action_candidates는 정확히 3개만 작성하세요.
같은 단어나 문장을 반복하지 마세요.
"""


def _thinking_config() -> types.ThinkingConfig:
    return types.ThinkingConfig(thinking_level="MINIMAL")


def _usage_row(*, filename: str, model: str, usage: TokenUsage, status: str, error: str = "") -> dict[str, object]:
    return {
        "filename": filename,
        "model": model,
        "prompt_tokens": usage.prompt_tokens,
        "output_tokens": usage.output_tokens,
        "thought_tokens": usage.thought_tokens,
        "total_tokens": usage.total_tokens,
        "calls": usage.calls,
        "status": status,
        "error": _clean_text(error, 500),
    }


def append_usage_log(row: dict[str, object]) -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    path = OUTPUT_DIR / "usage.csv"
    write_header = not path.exists()
    with path.open("a", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=list(row.keys()))
        if write_header:
            writer.writeheader()
        writer.writerow(row)


def persist_image(source_path: str | Path) -> dict[str, str]:
    source = Path(source_path)
    if not source.exists():
        raise FileNotFoundError(f"이미지를 찾을 수 없습니다: {source}")

    IMAGE_DIR.mkdir(parents=True, exist_ok=True)
    file_hash = hashlib.sha256(source.read_bytes()).hexdigest()
    image_id = file_hash[:16]
    suffix = source.suffix.lower() or ".jpg"
    stored_path = IMAGE_DIR / f"{image_id}{suffix}"

    if not stored_path.exists():
        shutil.copy2(source, stored_path)

    return {
        "image_id": image_id,
        "stored_path": str(stored_path),
        "original_name": source.name,
        "sha256": file_hash,
    }


class GeminiAnalyzer:
    def __init__(self, model: str = MODEL_NAME) -> None:
        api_key = os.getenv("GEMINI_API_KEY")
        if not api_key:
            raise RuntimeError("GEMINI_API_KEY가 없습니다. .env.example을 복사해 .env를 만들고 API 키를 입력하세요.")
        self.client = genai.Client(api_key=api_key)
        self.model = model
        (OUTPUT_DIR / "raw").mkdir(parents=True, exist_ok=True)

    def _image_part(self, image_path: str | Path) -> types.Part:
        path = Path(image_path)
        mime_type = mimetypes.guess_type(path.name)[0] or "image/jpeg"
        return types.Part.from_bytes(data=path.read_bytes(), mime_type=mime_type)

    def _save_raw(self, image_id: str, label: str, text: str) -> None:
        path = OUTPUT_DIR / "raw" / f"{image_id}_{label}.json.txt"
        path.write_text(text or "", encoding="utf-8")

    def _call(self, image_part: types.Part, prompt: str):
        return self.client.models.generate_content(
            model=self.model,
            contents=[prompt, image_part],
            config=types.GenerateContentConfig(
                temperature=0,
                max_output_tokens=MAX_OUTPUT_TOKENS,
                response_mime_type="application/json",
                response_schema=AnalysisResult,
                thinking_config=_thinking_config(),
            ),
        )

    def analyze(self, image_path: str | Path, image_id: str) -> AnalysisRun:
        usage = TokenUsage()
        image_part = self._image_part(image_path)
        result: AnalysisResult | None = None
        last_error: Exception | None = None

        for attempt, prompt in enumerate([MAIN_PROMPT, RETRY_PROMPT], start=1):
            response = self._call(image_part, prompt)
            usage.add(response)
            self._save_raw(image_id, f"full_{attempt}", response.text or "")
            try:
                result = AnalysisResult.model_validate_json(response.text or "")
                break
            except (ValidationError, json.JSONDecodeError) as error:
                last_error = error

        if result is None:
            raise RuntimeError(f"두 번 모두 유효한 JSON을 받지 못했습니다: {last_error}")

        status = "analyzed"
        return AnalysisRun(result=result, status=status, usage=usage, model=self.model)

    def close(self) -> None:
        self.client.close()


def analysis_to_candidate_rows(result: AnalysisResult) -> list[dict[str, object]]:
    return [
        {
            "selected": False,
            "title": item.title,
            "bucket_id": item.bucket_id,
            "subject": item.subject,
            "reason": item.reason,
        }
        for item in result.action_candidates
    ]


def candidate_rows_to_table(rows: list[dict]) -> list[list[object]]:
    return [
        [
            bool(row.get("selected", False)),
            row.get("title", ""),
            row.get("bucket_id", "reference.save"),
            row.get("subject", ""),
            row.get("reason", ""),
        ]
        for row in rows
    ]


def table_to_candidate_rows(table: object) -> list[dict[str, object]]:
    if table is None:
        return []

    if hasattr(table, "values"):
        raw_rows = table.values.tolist()
    else:
        raw_rows = list(table)

    output: list[dict[str, object]] = []
    for row in raw_rows:
        if not row or len(row) < 5:
            continue
        title = _clean_text(row[1], 100)
        if not title:
            continue
        bucket_id = str(row[2] or "reference.save").strip()
        if bucket_id not in BUCKETS:
            bucket_id = "reference.save"
        output.append(
            {
                "selected": bool(row[0]),
                "title": title,
                "bucket_id": bucket_id,
                "subject": _clean_text(row[3], 80),
                "reason": _clean_text(row[4], 120),
            }
        )
    return output
