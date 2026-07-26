from __future__ import annotations

import argparse
from pathlib import Path

from core import GeminiAnalyzer, _usage_row, analysis_to_candidate_rows, append_usage_log, persist_image
from database import init_db, is_analyzed, save_analysis

SUPPORTED_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp"}


def main() -> None:
    parser = argparse.ArgumentParser(description="폴더의 이미지를 Gemini 3.5 Flash-Lite로 분석해 SQLite에 저장합니다.")
    parser.add_argument("--input-dir", default="data/raw", help="원본 이미지 폴더. 기본값: data/raw")
    parser.add_argument("--limit", type=int, default=0, help="앞에서 N장만 처리합니다. 0이면 전체 처리.")
    parser.add_argument("--force", action="store_true", help="이미 분석된 이미지도 다시 분석합니다.")
    args = parser.parse_args()

    input_dir = Path(args.input_dir)
    if not input_dir.exists():
        raise SystemExit(f"입력 폴더가 없습니다: {input_dir}")

    images = [
        path for path in sorted(input_dir.iterdir())
        if path.is_file() and path.suffix.lower() in SUPPORTED_SUFFIXES
    ]
    if args.limit > 0:
        images = images[: args.limit]

    if not images:
        raise SystemExit(f"분석할 이미지가 없습니다: {input_dir}")

    init_db()
    analyzer = GeminiAnalyzer()

    success = 0
    failed = 0
    skipped = 0

    try:
        for index, image_path in enumerate(images, start=1):
            print(f"[{index}/{len(images)}] {image_path.name}")
            file_info = persist_image(image_path)

            if not args.force and is_analyzed(file_info["sha256"]):
                skipped += 1
                print("  건너뜀: 이미 저장된 이미지")
                continue

            try:
                run = analyzer.analyze(file_info["stored_path"], file_info["image_id"])
                candidates = analysis_to_candidate_rows(run.result)
                save_analysis(
                    file_info=file_info,
                    result=run.result,
                    candidates=candidates,
                    model=run.model,
                    status=run.status,
                )
                append_usage_log(
                    _usage_row(
                        filename=image_path.name,
                        model=run.model,
                        usage=run.usage,
                        status=run.status,
                    )
                )
                success += 1
                print(
                    "  저장 완료"
                    f" | 후보 {len(candidates)}개"
                    f" | 토큰 {run.usage.total_tokens:,}"
                    f" | 상태 {run.status}"
                )
            except Exception as error:
                failed += 1
                append_usage_log(
                    {
                        "filename": image_path.name,
                        "model": analyzer.model,
                        "prompt_tokens": 0,
                        "output_tokens": 0,
                        "thought_tokens": 0,
                        "total_tokens": 0,
                        "calls": 0,
                        "status": "failed",
                        "error": str(error)[:500],
                    }
                )
                print(f"  실패: {error}")
    finally:
        analyzer.close()

    print(f"\n완료 — 성공 {success}개 / 실패 {failed}개 / 건너뜀 {skipped}개")
    print("토큰 사용량: outputs/usage.csv")


if __name__ == "__main__":
    main()
