"""SQLite audit trail: runs, generated tests, node decisions, execution results.

Uses only the stdlib :mod:`sqlite3`. One :class:`AuditStore` wraps one database
file (``":memory:"`` works too). All writes go through a lock so the same
store can be shared by the pipeline and, later, the API's worker threads.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Self

from pydantic import BaseModel

from uds_assistant.testgen.model import ReviewStatus, TestCase

_SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    requirement_id TEXT NOT NULL,
    requirement_text TEXT NOT NULL,
    llm_mode TEXT NOT NULL,
    retriever TEXT NOT NULL,
    status TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS tests (
    run_id INTEGER NOT NULL REFERENCES runs(id),
    test_id TEXT NOT NULL,
    json TEXT NOT NULL,
    review_status TEXT NOT NULL,
    PRIMARY KEY (run_id, test_id)
);
CREATE TABLE IF NOT EXISTS decisions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id INTEGER NOT NULL REFERENCES runs(id),
    node TEXT NOT NULL,
    message TEXT NOT NULL,
    ts TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS results (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id INTEGER NOT NULL REFERENCES runs(id),
    test_id TEXT NOT NULL,
    passed INTEGER NOT NULL,
    details_json TEXT NOT NULL,
    bug_id TEXT,
    ts TEXT NOT NULL
);
"""


def _now() -> str:
    return datetime.now(UTC).isoformat()


class RunRecord(BaseModel):
    """One row of the ``runs`` table."""

    id: int
    started_at: str
    finished_at: str | None
    requirement_id: str
    requirement_text: str
    llm_mode: str
    retriever: str
    status: str


class DecisionRecord(BaseModel):
    """One row of the ``decisions`` table."""

    run_id: int
    node: str
    message: str
    ts: str


class ResultRecord(BaseModel):
    """One row of the ``results`` table."""

    run_id: int
    test_id: str
    passed: bool
    details: dict[str, Any]
    bug_id: str | None
    ts: str


class AuditStore:
    """SQLite-backed audit trail."""

    def __init__(self, path: str | Path) -> None:
        self.path = str(path)
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(self.path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        with self._lock, self._conn:
            self._conn.executescript(_SCHEMA)

    # ----------------------------------------------------------------------- lifecycle

    def close(self) -> None:
        """Close the underlying connection."""
        self._conn.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def _exec(self, sql: str, params: tuple[Any, ...] = ()) -> sqlite3.Cursor:
        with self._lock, self._conn:
            return self._conn.execute(sql, params)

    def _query(self, sql: str, params: tuple[Any, ...] = ()) -> list[sqlite3.Row]:
        with self._lock:
            return list(self._conn.execute(sql, params).fetchall())

    # -------------------------------------------------------------------------- runs

    def start_run(
        self, requirement_id: str, requirement_text: str, llm_mode: str, retriever: str
    ) -> int:
        """Create a run row with status ``running`` and return its id."""
        cur = self._exec(
            "INSERT INTO runs (started_at, requirement_id, requirement_text, llm_mode, retriever,"
            " status) VALUES (?, ?, ?, ?, ?, 'running')",
            (_now(), requirement_id, requirement_text, llm_mode, retriever),
        )
        assert cur.lastrowid is not None
        return int(cur.lastrowid)

    def finish_run(self, run_id: int, status: str) -> None:
        """Set a run's final status (e.g. ``completed``/``failed``)."""
        self._exec(
            "UPDATE runs SET status = ?, finished_at = ? WHERE id = ?", (status, _now(), run_id)
        )

    def get_run(self, run_id: int) -> RunRecord | None:
        """Fetch one run, or None."""
        rows = self._query("SELECT * FROM runs WHERE id = ?", (run_id,))
        return RunRecord(**dict(rows[0])) if rows else None

    def list_runs(self, requirement_id: str | None = None) -> list[RunRecord]:
        """All runs (optionally for one requirement), oldest first."""
        if requirement_id is None:
            rows = self._query("SELECT * FROM runs ORDER BY id")
        else:
            rows = self._query(
                "SELECT * FROM runs WHERE requirement_id = ? ORDER BY id", (requirement_id,)
            )
        return [RunRecord(**dict(r)) for r in rows]

    # ------------------------------------------------------------------------- tests

    def record_test(self, run_id: int, test: TestCase) -> None:
        """Insert or replace a generated test (its full JSON and review status)."""
        self._exec(
            "INSERT OR REPLACE INTO tests (run_id, test_id, json, review_status)"
            " VALUES (?, ?, ?, ?)",
            (run_id, test.id, test.model_dump_json(), test.review_status),
        )

    def set_review_status(self, run_id: int, test_id: str, status: ReviewStatus) -> None:
        """Update a stored test's review status (also inside its JSON)."""
        rows = self._query(
            "SELECT json FROM tests WHERE run_id = ? AND test_id = ?", (run_id, test_id)
        )
        if not rows:
            raise KeyError(f"no test {test_id!r} in run {run_id}")
        test = TestCase.model_validate_json(rows[0]["json"]).model_copy(
            update={"review_status": status}
        )
        self.record_test(run_id, test)

    def get_tests(self, run_id: int) -> list[TestCase]:
        """All tests stored for a run, in insertion order."""
        rows = self._query("SELECT json FROM tests WHERE run_id = ? ORDER BY rowid", (run_id,))
        return [TestCase.model_validate_json(r["json"]) for r in rows]

    # --------------------------------------------------------------------- decisions

    def record_decision(self, run_id: int, node: str, message: str) -> None:
        """Append one node decision to the audit trail."""
        self._exec(
            "INSERT INTO decisions (run_id, node, message, ts) VALUES (?, ?, ?, ?)",
            (run_id, node, message, _now()),
        )

    def get_decisions(self, run_id: int, node: str | None = None) -> list[DecisionRecord]:
        """Decisions for a run (optionally one node), in order."""
        sql = "SELECT run_id, node, message, ts FROM decisions WHERE run_id = ?"
        params: tuple[Any, ...] = (run_id,)
        if node is not None:
            sql += " AND node = ?"
            params += (node,)
        rows = self._query(sql + " ORDER BY id", params)
        return [DecisionRecord(**dict(r)) for r in rows]

    # ----------------------------------------------------------------------- results

    def record_result(
        self,
        run_id: int,
        test_id: str,
        passed: bool,
        details: dict[str, Any] | None = None,
        bug_id: str | None = None,
    ) -> None:
        """Record one execution result (``bug_id`` = injected bug, None for clean ECU)."""
        self._exec(
            "INSERT INTO results (run_id, test_id, passed, details_json, bug_id, ts)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (run_id, test_id, int(passed), json.dumps(details or {}, sort_keys=True), bug_id,
             _now()),
        )

    def get_results(
        self, run_id: int, *, bug_id: str | None = None, any_bug: bool = True
    ) -> list[ResultRecord]:
        """Results for a run. With ``any_bug=False`` only rows matching ``bug_id``
        (``None`` meaning the clean ECU) are returned."""
        sql = "SELECT * FROM results WHERE run_id = ?"
        params: tuple[Any, ...] = (run_id,)
        if not any_bug:
            if bug_id is None:
                sql += " AND bug_id IS NULL"
            else:
                sql += " AND bug_id = ?"
                params += (bug_id,)
        rows = self._query(sql + " ORDER BY id", params)
        return [
            ResultRecord(
                run_id=r["run_id"],
                test_id=r["test_id"],
                passed=bool(r["passed"]),
                details=json.loads(r["details_json"]),
                bug_id=r["bug_id"],
                ts=r["ts"],
            )
            for r in rows
        ]
