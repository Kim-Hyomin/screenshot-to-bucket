from __future__ import annotations

import gradio as gr
import pandas as pd

from core import (
    BUCKETS,
    CANDIDATE_COLUMNS,
    SOURCE_TYPES,
    GeminiAnalyzer,
    _usage_row,
    analysis_to_candidate_rows,
    append_usage_log,
    candidate_rows_to_table,
    persist_image,
    table_to_candidate_rows,
)
from database import get_image, init_db, list_images, save_analysis, search_images, update_candidates

init_db()


def _candidate_dataframe(rows: list[dict]) -> pd.DataFrame:
    return pd.DataFrame(candidate_rows_to_table(rows), columns=CANDIDATE_COLUMNS)


def analyze_image(image_path: str | None):
    if not image_path:
        raise gr.Error("이미지를 먼저 업로드하세요.")

    file_info = persist_image(image_path)
    analyzer = GeminiAnalyzer()
    try:
        run = analyzer.analyze(file_info["stored_path"], file_info["image_id"])
    finally:
        analyzer.close()

    candidates = analysis_to_candidate_rows(run.result)
    state = {
        "file_info": file_info,
        "analysis": run.result.model_dump(),
        "model": run.model,
        "status": run.status,
    }

    append_usage_log(
        _usage_row(
            filename=file_info["original_name"],
            model=run.model,
            usage=run.usage,
            status=run.status,
        )
    )

    return (
        run.result.summary,
        run.result.model_dump(),
        _candidate_dataframe(candidates),
        state,
        f"분석 완료 · 후보 {len(candidates)}개 · 총 토큰 {run.usage.total_tokens:,}개",
    )


def save_new_analysis(state: dict | None, candidate_table):
    if not state:
        raise gr.Error("먼저 이미지를 분석하세요.")

    from core import AnalysisResult

    result = AnalysisResult.model_validate(state["analysis"])
    candidates = table_to_candidate_rows(candidate_table)
    status = "analyzed" if len(candidates) >= 1 else "needs_review"

    save_analysis(
        file_info=state["file_info"],
        result=result,
        candidates=candidates,
        model=state["model"],
        status=status,
    )
    selected_count = sum(bool(item["selected"]) for item in candidates)
    return f"저장 완료 · 후보 {len(candidates)}개 · 선택된 후보 {selected_count}개"


def refresh_review_choices():
    choices = list_images()
    value = choices[0][1] if choices else None
    return gr.update(choices=choices, value=value)


def load_review(image_id: str | None):
    if not image_id:
        return None, "", {}, pd.DataFrame(columns=CANDIDATE_COLUMNS)

    record = get_image(image_id)
    if record is None:
        raise gr.Error("저장된 이미지를 찾을 수 없습니다.")

    return (
        record["image"]["stored_path"],
        record["image"]["summary"],
        record["analysis"],
        _candidate_dataframe(record["candidates"]),
    )


def save_review(image_id: str | None, candidate_table):
    if not image_id:
        raise gr.Error("검토할 이미지를 선택하세요.")

    candidates = table_to_candidate_rows(candidate_table)
    update_candidates(image_id, candidates)
    selected_count = sum(bool(item["selected"]) for item in candidates)
    return f"수정 완료 · 후보 {len(candidates)}개 · 선택된 후보 {selected_count}개"


def run_search(query: str, bucket_id: str):
    rows = search_images(query or "", bucket_id or "전체")
    gallery = [(row["path"], row["summary"]) for row in rows]
    table = pd.DataFrame(
        [
            {
                "파일": row["original_name"],
                "요약": row["summary"],
                "출처": row["source"],
                "콘텐츠 날짜": row["dates"],
                "선택 버킷": row["buckets"],
                "태그": row["tags"],
                "상태": row["status"],
            }
            for row in rows
        ],
        columns=["파일", "요약", "출처", "콘텐츠 날짜", "선택 버킷", "태그", "상태"],
    )
    return gallery, table, f"검색 결과: {len(rows)}개"


BUCKET_GUIDE = "\n".join(f"- `{bucket_id}`: {label}" for bucket_id, label in BUCKETS.items())
SOURCE_GUIDE = "\n".join(f"- `{source_id}`: {label}" for source_id, label in SOURCE_TYPES.items())

with gr.Blocks(title="Screenshot to Bucket", fill_width=True) as demo:
    gr.Markdown(
        """
        # Screenshot to Bucket
        Gemini 3.5 Flash-Lite가 **한 번의 이미지 호출**로
        메타데이터와 행동 후보 3개를 함께 생성하는 PoC입니다.
        """
    )

    with gr.Tab("1. 새 이미지 분석"):
        with gr.Row():
            image_input = gr.Image(type="filepath", label="스크린샷", sources=["upload", "clipboard"], scale=1)
            with gr.Column(scale=2):
                summary_output = gr.Textbox(label="요약", interactive=False)
                status_output = gr.Markdown()

        analyze_button = gr.Button("분석하기", variant="primary")
        metadata_output = gr.JSON(label="추출 메타데이터")
        gr.Markdown(
            """
            ### 행동 후보
            - 기본적으로 후보 3개가 생성됩니다.
            - 후보는 화면의 특정 요소를 반영할 수도 있고, 전체 화면의 공통 주제를 포괄할 수도 있습니다.
            - `선택`을 체크하고 제목·버킷·대상·이유를 수정할 수 있습니다.
            """
        )
        candidate_table = gr.Dataframe(
            headers=CANDIDATE_COLUMNS,
            datatype=["bool", "str", "str", "str", "str"],
            type="pandas",
            row_count=(5, "dynamic"),
            col_count=(5, "fixed"),
            interactive=True,
            wrap=True,
            label="행동 후보",
        )
        with gr.Accordion("버킷 ID 안내", open=False):
            gr.Markdown(BUCKET_GUIDE)
        with gr.Accordion("출처 유형 안내", open=False):
            gr.Markdown(SOURCE_GUIDE)

        save_button = gr.Button("선택 결과 저장")
        analysis_state = gr.State()

        analyze_button.click(
            fn=analyze_image,
            inputs=image_input,
            outputs=[summary_output, metadata_output, candidate_table, analysis_state, status_output],
        )
        save_button.click(fn=save_new_analysis, inputs=[analysis_state, candidate_table], outputs=status_output)

    with gr.Tab("2. 저장 결과 검토"):
        with gr.Row():
            review_choice = gr.Dropdown(choices=list_images(), label="검토할 이미지", type="value", scale=4)
            refresh_button = gr.Button("목록 새로고침", scale=1)

        load_button = gr.Button("불러오기")
        with gr.Row():
            review_image = gr.Image(label="저장된 이미지", interactive=False, scale=1)
            with gr.Column(scale=2):
                review_summary = gr.Textbox(label="요약", interactive=False)
                review_metadata = gr.JSON(label="메타데이터")

        review_table = gr.Dataframe(
            headers=CANDIDATE_COLUMNS,
            datatype=["bool", "str", "str", "str", "str"],
            type="pandas",
            row_count=(5, "dynamic"),
            col_count=(5, "fixed"),
            interactive=True,
            wrap=True,
            label="후보 선택·수정",
        )
        review_status = gr.Markdown()
        review_save_button = gr.Button("수정 내용 저장", variant="primary")

        refresh_button.click(fn=refresh_review_choices, outputs=review_choice)
        load_button.click(fn=load_review, inputs=review_choice, outputs=[review_image, review_summary, review_metadata, review_table])
        review_save_button.click(fn=save_review, inputs=[review_choice, review_table], outputs=review_status)

    with gr.Tab("3. 버킷·검색"):
        with gr.Row():
            search_query = gr.Textbox(label="검색어", placeholder="예: 토마토 요리, 독서 리스트, 안동 여행, 하객룩", scale=4)
            bucket_filter = gr.Dropdown(
                choices=[("전체", "전체")] + [(label, bucket_id) for bucket_id, label in BUCKETS.items()],
                value="전체",
                label="버킷",
                scale=2,
            )
            search_button = gr.Button("검색", variant="primary", scale=1)

        search_status = gr.Markdown()
        search_gallery = gr.Gallery(label="이미지 결과", columns=4, object_fit="contain", height=520, allow_preview=True)
        search_table = gr.Dataframe(
            headers=["파일", "요약", "출처", "콘텐츠 날짜", "선택 버킷", "태그", "상태"],
            type="pandas",
            interactive=False,
            wrap=True,
            label="검색 결과 메타데이터",
        )

        search_button.click(fn=run_search, inputs=[search_query, bucket_filter], outputs=[search_gallery, search_table, search_status])
        demo.load(fn=run_search, inputs=[search_query, bucket_filter], outputs=[search_gallery, search_table, search_status])


if __name__ == "__main__":
    demo.launch()
