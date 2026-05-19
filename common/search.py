"""
FTS5 full-text search for planner apps.

Creates external-content FTS5 virtual tables linked to real tables,
with triggers to keep the index in sync on INSERT/UPDATE/DELETE.
"""
from __future__ import annotations

import sqlite3


# ── FTS table definitions ──
# Each entry: (fts_table, content_table, indexed_columns)
_FTS_TABLES: list[tuple[str, str, list[str]]] = [
    ("fts_todos",    "todos",      ["title", "description"]),
    ("fts_memos",    "memos",      ["content"]),
    ("fts_notices",  "notices",    ["title", "content"]),
    ("fts_events",   "events",     ["title", "memo"]),
    ("fts_worklogs", "work_logs",  ["title", "content"]),
    ("fts_entries",  "form_entries", ["values_json"]),
]


def init_fts(conn: sqlite3.Connection) -> None:
    """Create FTS5 virtual tables and sync triggers.

    Safe to call repeatedly -- uses IF NOT EXISTS and checks for
    existing triggers before creating.
    """
    for fts_tbl, content_tbl, cols in _FTS_TABLES:
        col_list = ", ".join(cols)

        # Create external-content FTS5 table
        conn.execute(
            f"CREATE VIRTUAL TABLE IF NOT EXISTS {fts_tbl} "
            f"USING fts5({col_list}, content={content_tbl}, content_rowid=id, "
            f"tokenize='unicode61')"
        )

        # Check if triggers already exist to avoid duplicates
        existing = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='trigger' AND name=?",
            (f"{fts_tbl}_ai",),
        ).fetchone()
        if existing:
            continue

        # Build column references for triggers
        new_cols = ", ".join(f"new.{c}" for c in cols)
        old_cols = ", ".join(f"old.{c}" for c in cols)

        # INSERT trigger
        conn.execute(f"""
            CREATE TRIGGER {fts_tbl}_ai AFTER INSERT ON {content_tbl} BEGIN
                INSERT INTO {fts_tbl}(rowid, {col_list})
                VALUES (new.id, {new_cols});
            END
        """)

        # DELETE trigger
        conn.execute(f"""
            CREATE TRIGGER {fts_tbl}_ad AFTER DELETE ON {content_tbl} BEGIN
                INSERT INTO {fts_tbl}({fts_tbl}, rowid, {col_list})
                VALUES ('delete', old.id, {old_cols});
            END
        """)

        # UPDATE trigger
        conn.execute(f"""
            CREATE TRIGGER {fts_tbl}_au AFTER UPDATE ON {content_tbl} BEGIN
                INSERT INTO {fts_tbl}({fts_tbl}, rowid, {col_list})
                VALUES ('delete', old.id, {old_cols});
                INSERT INTO {fts_tbl}(rowid, {col_list})
                VALUES (new.id, {new_cols});
            END
        """)

    # Rebuild all FTS indexes to sync with existing data
    for fts_tbl, _, _ in _FTS_TABLES:
        conn.execute(f"INSERT INTO {fts_tbl}({fts_tbl}) VALUES('rebuild')")

    conn.commit()


def search_fts(
    conn: sqlite3.Connection,
    query: str,
    pid: int,
    limit: int = 50,
) -> dict:
    """Run FTS5 search across all entity types.

    Returns a dict with the same keys as the old LIKE-based search:
      todos, events, memos, notices, worklogs, entries
    Each value is a list of dicts with id, display fields, and snippet.
    """
    # Escape FTS5 special characters and wrap each token in quotes
    # to avoid syntax errors on user input with special chars.
    safe_q = _escape_fts_query(query)
    if not safe_q:
        return _empty_results()

    per_type = max(5, limit // 6)
    results: dict = {}

    # ── Todos ──
    results["todos"] = _query_fts(
        conn, safe_q, pid, per_type,
        fts_table="fts_todos",
        content_table="todos",
        select_cols="t.id, t.title, t.due_date",
        snippet_col=0,
        snippet_label="snippet",
    )

    # ── Events ──
    results["events"] = _query_fts(
        conn, safe_q, pid, per_type,
        fts_table="fts_events",
        content_table="events",
        select_cols="t.id, t.title, t.start_time",
        snippet_col=0,
        snippet_label="snippet",
    )

    # ── Memos ──
    results["memos"] = _query_fts(
        conn, safe_q, pid, per_type,
        fts_table="fts_memos",
        content_table="memos",
        select_cols="t.id, t.content, t.created_at",
        snippet_col=0,
        snippet_label="snippet",
    )

    # ── Notices ──
    results["notices"] = _query_fts(
        conn, safe_q, pid, per_type,
        fts_table="fts_notices",
        content_table="notices",
        select_cols="t.id, t.title, t.created_at",
        snippet_col=0,
        snippet_label="snippet",
    )

    # ── Work logs ──
    results["worklogs"] = _query_fts(
        conn, safe_q, pid, per_type,
        fts_table="fts_worklogs",
        content_table="work_logs",
        select_cols="t.id, t.content, t.log_date",
        snippet_col=0,
        snippet_label="snippet",
    )

    # ── Form entries ──
    results["entries"] = _query_fts_entries(conn, safe_q, pid, per_type)

    return results


# ── Internal helpers ──

def _empty_results() -> dict:
    return {
        "todos": [], "events": [], "memos": [],
        "notices": [], "worklogs": [], "entries": [],
    }


def _escape_fts_query(raw: str) -> str:
    """Convert user input to a safe FTS5 query.

    Strategy: strip FTS5 operators, wrap each token in double quotes
    so Korean text and special characters are treated as literal strings.
    """
    # Remove FTS5 syntax characters
    cleaned = raw.replace('"', " ")
    for ch in ("*", "(", ")", ":", "^", "{", "}", "+"):
        cleaned = cleaned.replace(ch, " ")
    tokens = cleaned.split()
    if not tokens:
        return ""
    # Quote each token and join with implicit AND
    return " ".join(f'"{t}"' for t in tokens)


def _query_fts(
    conn: sqlite3.Connection,
    fts_query: str,
    pid: int,
    limit: int,
    *,
    fts_table: str,
    content_table: str,
    select_cols: str,
    snippet_col: int,
    snippet_label: str,
) -> list[dict]:
    """Execute a single-entity FTS5 query with snippet and profile filter."""
    sql = f"""
        SELECT {select_cols},
               snippet({fts_table}, {snippet_col}, '<mark>', '</mark>', '...', 30) AS {snippet_label}
        FROM {fts_table} f
        JOIN {content_table} t ON t.id = f.rowid
        WHERE {fts_table} MATCH ?
          AND t.profile_id = ?
        ORDER BY rank
        LIMIT ?
    """
    try:
        rows = conn.execute(sql, (fts_query, pid, limit)).fetchall()
        return [dict(r) for r in rows]
    except sqlite3.OperationalError:
        # FTS table may not exist yet or query syntax error -- degrade gracefully
        return []


def _query_fts_entries(
    conn: sqlite3.Connection,
    fts_query: str,
    pid: int,
    limit: int,
) -> list[dict]:
    """FTS query for form_entries with template name join."""
    sql = """
        SELECT t.id, t.entry_date, t.values_json,
               ft.name AS tpl_name, ft.id AS tpl_id,
               snippet(fts_entries, 0, '<mark>', '</mark>', '...', 30) AS snippet
        FROM fts_entries f
        JOIN form_entries t ON t.id = f.rowid
        JOIN form_templates ft ON t.template_id = ft.id
        WHERE fts_entries MATCH ?
          AND t.profile_id = ?
        ORDER BY rank
        LIMIT ?
    """
    try:
        rows = conn.execute(sql, (fts_query, pid, limit)).fetchall()
        return [dict(r) for r in rows]
    except sqlite3.OperationalError:
        return []
