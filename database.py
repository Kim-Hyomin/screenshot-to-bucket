from __future__ import annotations

import json
import os
import re
import sqlite3
import uuid
from pathlib import Path

from core import AnalysisResult, BUCKETS, SOURCE_TYPES

DB_PATH = Path(os.getenv("DB_PATH", "data/app_g35.db"))


def connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(DB_PATH)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA journal_mode = WAL")
    return connection


def init_db() -> None:
    with connect() as connection:
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS images (
                id TEXT PRIMARY KEY,
                stored_path TEXT NOT NULL,
                original_name TEXT NOT NULL,
                sha256 TEXT NOT NULL UNIQUE,
                uploaded_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                model TEXT NOT NULL,
                status TEXT NOT NULL,
                summary TEXT NOT NULL,
                key_text TEXT NOT NULL,
                source_type TEXT NOT NULL,
                source_name TEXT,
                content_dates_json TEXT NOT NULL,
                objects_json TEXT NOT NULL,
                colors_json TEXT NOT NULL,
                places_json TEXT NOT NULL,
                activities_json TEXT NOT NULL,
                keywords_json TEXT NOT NULL,
                analysis_json TEXT NOT NULL,
                factual_search_text TEXT NOT NULL,
                intent_search_text TEXT NOT NULL DEFAULT ''
            );

            CREATE TABLE IF NOT EXISTS candidates (
                id TEXT PRIMARY KEY,
                image_id TEXT NOT NULL,
                title TEXT NOT NULL,
                bucket_id TEXT NOT NULL,
                subject TEXT NOT NULL,
                reason TEXT NOT NULL,
                selected INTEGER NOT NULL DEFAULT 0,
                FOREIGN KEY (image_id) REFERENCES images(id) ON DELETE CASCADE
            );

            CREATE INDEX IF NOT EXISTS idx_candidates_image ON candidates(image_id);
            CREATE INDEX IF NOT EXISTS idx_candidates_bucket ON candidates(bucket_id);
            """
        )
        try:
            connection.execute(
                """
                CREATE VIRTUAL TABLE IF NOT EXISTS image_fts
                USING fts5(
                    image_id UNINDEXED,
                    factual_search_text,
                    intent_search_text,
                    tokenize='unicode61'
                )
                """
            )
        except sqlite3.OperationalError:
            pass


def _factual_text(result: AnalysisResult) -> str:
    values: list[str] = [
        result.summary,
        result.key_text,
        SOURCE_TYPES.get(result.source_type, result.source_type),
        result.source_name or "",
        *result.content_dates,
        *result.objects,
        *result.colors,
        *result.places,
        *result.activities,
        *result.keywords,
    ]
    return " ".join(value for value in values if value)


def _intent_text(candidates: list[dict]) -> str:
    values: list[str] = []
    for item in candidates:
        if not item.get("selected"):
            continue
        bucket_id = str(item.get("bucket_id", "reference.save"))
        values.extend(
            [
                str(item.get("title", "")),
                str(item.get("subject", "")),
                BUCKETS.get(bucket_id, bucket_id),
                str(item.get("reason", "")),
            ]
        )
    return " ".join(value for value in values if value)


def _rebuild_fts(connection: sqlite3.Connection, image_id: str, factual_text: str, intent_text: str) -> None:
    try:
        connection.execute("DELETE FROM image_fts WHERE image_id = ?", (image_id,))
        connection.execute(
            """
            INSERT INTO image_fts (image_id, factual_search_text, intent_search_text)
            VALUES (?, ?, ?)
            """,
            (image_id, factual_text, intent_text),
        )
    except sqlite3.OperationalError:
        pass


def save_analysis(*, file_info: dict[str, str], result: AnalysisResult, candidates: list[dict], model: str, status: str) -> None:
    factual_text = _factual_text(result)
    intent_text = _intent_text(candidates)

    with connect() as connection:
        connection.execute(
            """
            INSERT INTO images (
                id, stored_path, original_name, sha256, model, status,
                summary, key_text, source_type, source_name,
                content_dates_json, objects_json, colors_json, places_json,
                activities_json, keywords_json, analysis_json,
                factual_search_text, intent_search_text
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                stored_path=excluded.stored_path,
                original_name=excluded.original_name,
                sha256=excluded.sha256,
                model=excluded.model,
                status=excluded.status,
                summary=excluded.summary,
                key_text=excluded.key_text,
                source_type=excluded.source_type,
                source_name=excluded.source_name,
                content_dates_json=excluded.content_dates_json,
                objects_json=excluded.objects_json,
                colors_json=excluded.colors_json,
                places_json=excluded.places_json,
                activities_json=excluded.activities_json,
                keywords_json=excluded.keywords_json,
                analysis_json=excluded.analysis_json,
                factual_search_text=excluded.factual_search_text,
                intent_search_text=excluded.intent_search_text
            """,
            (
                file_info["image_id"],
                file_info["stored_path"],
                file_info["original_name"],
                file_info["sha256"],
                model,
                status,
                result.summary,
                result.key_text,
                result.source_type,
                result.source_name,
                json.dumps(result.content_dates, ensure_ascii=False),
                json.dumps(result.objects, ensure_ascii=False),
                json.dumps(result.colors, ensure_ascii=False),
                json.dumps(result.places, ensure_ascii=False),
                json.dumps(result.activities, ensure_ascii=False),
                json.dumps(result.keywords, ensure_ascii=False),
                result.model_dump_json(),
                factual_text,
                intent_text,
            ),
        )

        connection.execute("DELETE FROM candidates WHERE image_id = ?", (file_info["image_id"],))
        for item in candidates:
            connection.execute(
                """
                INSERT INTO candidates (id, image_id, title, bucket_id, subject, reason, selected)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    uuid.uuid4().hex,
                    file_info["image_id"],
                    item["title"],
                    item["bucket_id"],
                    item["subject"],
                    item["reason"],
                    int(bool(item["selected"])),
                ),
            )

        _rebuild_fts(connection, file_info["image_id"], factual_text, intent_text)


def is_analyzed(sha256: str) -> bool:
    with connect() as connection:
        row = connection.execute("SELECT 1 FROM images WHERE sha256 = ? LIMIT 1", (sha256,)).fetchone()
    return row is not None


def list_images() -> list[tuple[str, str]]:
    with connect() as connection:
        rows = connection.execute(
            """
            SELECT id, original_name, summary, status
            FROM images
            ORDER BY uploaded_at DESC
            """
        ).fetchall()

    choices = []
    for row in rows:
        warning = " ⚠ 수동 검토 필요" if row["status"] == "needs_review" else ""
        choices.append((f"{row['original_name']} — {row['summary'][:45]}{warning}", row["id"]))
    return choices


def get_image(image_id: str) -> dict | None:
    with connect() as connection:
        image = connection.execute("SELECT * FROM images WHERE id = ?", (image_id,)).fetchone()
        if image is None:
            return None

        candidates = connection.execute(
            """
            SELECT title, bucket_id, subject, reason, selected
            FROM candidates
            WHERE image_id = ?
            ORDER BY rowid
            """,
            (image_id,),
        ).fetchall()

    return {
        "image": dict(image),
        "analysis": json.loads(image["analysis_json"]),
        "candidates": [dict(row) for row in candidates],
    }


def update_candidates(image_id: str, candidates: list[dict]) -> None:
    with connect() as connection:
        connection.execute("DELETE FROM candidates WHERE image_id = ?", (image_id,))
        for item in candidates:
            connection.execute(
                """
                INSERT INTO candidates (id, image_id, title, bucket_id, subject, reason, selected)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    uuid.uuid4().hex,
                    image_id,
                    item["title"],
                    item["bucket_id"],
                    item["subject"],
                    item["reason"],
                    int(bool(item["selected"])),
                ),
            )

        intent_text = _intent_text(candidates)
        connection.execute(
            """
            UPDATE images
            SET intent_search_text = ?,
                status = CASE WHEN ? >= 1 THEN 'analyzed' ELSE 'needs_review' END
            WHERE id = ?
            """,
            (intent_text, len(candidates), image_id),
        )

        row = connection.execute("SELECT factual_search_text FROM images WHERE id = ?", (image_id,)).fetchone()
        if row:
            _rebuild_fts(connection, image_id, row["factual_search_text"], intent_text)


def _safe_fts_query(query: str) -> str:
    tokens = re.findall(r"[0-9A-Za-z가-힣_]+", query)
    return " AND ".join(f'"{token}"' for token in tokens)


def search_images(query: str = "", bucket_id: str = "전체") -> list[dict]:
    query = query.strip()
    parameters: list = []
    filters: list[str] = []

    if bucket_id != "전체":
        filters.append(
            """
            EXISTS (
                SELECT 1 FROM candidates c
                WHERE c.image_id = i.id
                  AND c.selected = 1
                  AND c.bucket_id = ?
            )
            """
        )
        parameters.append(bucket_id)

    base_sql = """
        SELECT DISTINCT
            i.id, i.stored_path, i.original_name, i.summary,
            i.source_type, i.source_name, i.content_dates_json,
            i.objects_json, i.colors_json, i.places_json,
            i.activities_json, i.keywords_json, i.status
        FROM images i
    """

    rows: list[sqlite3.Row] = []
    with connect() as connection:
        if query:
            fts_query = _safe_fts_query(query)
            if fts_query:
                try:
                    fts_filters = list(filters)
                    fts_filters.append(
                        """
                        i.id IN (
                            SELECT image_id FROM image_fts
                            WHERE image_fts MATCH ?
                        )
                        """
                    )
                    sql = base_sql + " WHERE " + " AND ".join(fts_filters)
                    sql += " ORDER BY i.uploaded_at DESC"
                    rows = connection.execute(sql, [*parameters, fts_query]).fetchall()
                except sqlite3.OperationalError:
                    rows = []

            if not rows:
                like_filters = list(filters)
                like_parameters = list(parameters)
                for token in re.findall(r"[0-9A-Za-z가-힣_]+", query):
                    like_filters.append("(i.factual_search_text LIKE ? OR i.intent_search_text LIKE ?)")
                    like_parameters.extend([f"%{token}%", f"%{token}%"])
                sql = base_sql
                if like_filters:
                    sql += " WHERE " + " AND ".join(like_filters)
                sql += " ORDER BY i.uploaded_at DESC"
                rows = connection.execute(sql, like_parameters).fetchall()
        else:
            sql = base_sql
            if filters:
                sql += " WHERE " + " AND ".join(filters)
            sql += " ORDER BY i.uploaded_at DESC"
            rows = connection.execute(sql, parameters).fetchall()

        output: list[dict] = []
        for row in rows:
            buckets = connection.execute(
                """
                SELECT DISTINCT bucket_id
                FROM candidates
                WHERE image_id = ? AND selected = 1
                ORDER BY bucket_id
                """,
                (row["id"],),
            ).fetchall()

            tag_values: list[str] = []
            for column in ["objects_json", "colors_json", "places_json", "activities_json", "keywords_json"]:
                tag_values.extend(json.loads(row[column]))

            output.append(
                {
                    "id": row["id"],
                    "path": row["stored_path"],
                    "original_name": row["original_name"],
                    "summary": row["summary"],
                    "source": " / ".join(value for value in [SOURCE_TYPES.get(row["source_type"], row["source_type"]), row["source_name"]] if value),
                    "dates": ", ".join(json.loads(row["content_dates_json"])),
                    "buckets": ", ".join(BUCKETS.get(item["bucket_id"], item["bucket_id"]) for item in buckets),
                    "tags": ", ".join(dict.fromkeys(tag_values)),
                    "status": row["status"],
                }
            )

    return output
