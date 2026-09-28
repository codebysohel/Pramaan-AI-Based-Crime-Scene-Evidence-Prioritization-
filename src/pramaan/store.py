"""Persistence: cases + a tamper-evident chain-of-custody ledger (SQLite).

Ledger design
-------------
Every event — a triage run, a re-score, a custody hand-over, and every action
an MCP client takes through the tools — is appended as:

    hash_n = SHA-256( canonical_json({seq, ts, case_id, item_id, actor, action,
                                      payload, prev_hash = hash_{n-1}}) )

Editing, deleting or re-ordering any row breaks every later hash, which
``verify()`` detects and localises. Triage results are not stored in the ledger
itself; their SHA-256 is, so ``verify_case()`` can prove a stored result was not
altered after the fact. The head hash is printed on each FSL submission packet,
letting the lab verify the packet against the IO's ledger.

Concurrency: the stdio MCP server process and the API server may append at the same
time; WAL mode + ``BEGIN IMMEDIATE`` serialises appends so the chain never forks.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from .config import get_settings

GENESIS = "0" * 64

_SCHEMA = """
CREATE TABLE IF NOT EXISTS cases (
    case_id     TEXT PRIMARY KEY,
    case_ref    TEXT NOT NULL,
    crime_type  TEXT NOT NULL,
    title       TEXT,
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL,
    kb_hash     TEXT NOT NULL,
    input_json  TEXT NOT NULL,
    result_json TEXT NOT NULL,
    result_sha256 TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS case_ai (
    case_id     TEXT PRIMARY KEY,
    updated_at  TEXT NOT NULL,
    ai_json     TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS ledger (
    seq       INTEGER PRIMARY KEY,
    ts        TEXT NOT NULL,
    case_id   TEXT,
    item_id   TEXT,
    actor     TEXT NOT NULL,
    action    TEXT NOT NULL,
    payload   TEXT NOT NULL,
    prev_hash TEXT NOT NULL,
    hash      TEXT NOT NULL UNIQUE
);
CREATE INDEX IF NOT EXISTS ledger_case ON ledger(case_id);
"""


def canonical(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def entry_hash(entry: dict[str, Any]) -> str:
    fields = {k: entry[k] for k in ("seq", "ts", "case_id", "item_id", "actor", "action", "payload", "prev_hash")}
    return sha256_text(canonical(fields))


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


class Store:
    def __init__(self, db_path: Path | str | None = None) -> None:
        settings = get_settings()
        self.db_path = Path(db_path) if db_path else settings.db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._conn() as c:
            c.executescript(_SCHEMA)

    @contextmanager
    def _conn(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.db_path, timeout=15, isolation_level=None)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=15000")
        try:
            yield conn
        finally:
            conn.close()

    # --------------------------------------------------------------- ledger
    def append(self, actor: str, action: str, payload: dict[str, Any] | None = None,
               case_id: str | None = None, item_id: str | None = None) -> dict[str, Any]:
        with self._conn() as c:
            c.execute("BEGIN IMMEDIATE")
            try:
                row = c.execute("SELECT seq, hash FROM ledger ORDER BY seq DESC LIMIT 1").fetchone()
                entry = {
                    "seq": (row["seq"] + 1) if row else 1,
                    "ts": utcnow(), "case_id": case_id, "item_id": item_id,
                    "actor": actor, "action": action, "payload": canonical(payload or {}),
                    "prev_hash": row["hash"] if row else GENESIS,
                }
                entry["hash"] = entry_hash(entry)
                c.execute(
                    "INSERT INTO ledger(seq, ts, case_id, item_id, actor, action, payload, prev_hash, hash) "
                    "VALUES(:seq, :ts, :case_id, :item_id, :actor, :action, :payload, :prev_hash, :hash)", entry,
                )
                c.execute("COMMIT")
            except Exception:
                c.execute("ROLLBACK")
                raise
        try:  # human-readable mirror; the SQLite chain remains the source of truth
            with open(self.db_path.parent / "audit.jsonl", "a", encoding="utf-8") as fh:
                fh.write(canonical(entry) + "\n")
        except OSError:
            pass
        return entry

    def ledger(self, case_id: str | None = None, limit: int = 500) -> list[dict[str, Any]]:
        with self._conn() as c:
            if case_id:
                rows = c.execute("SELECT * FROM ledger WHERE case_id=? ORDER BY seq DESC LIMIT ?", (case_id, limit))
            else:
                rows = c.execute("SELECT * FROM ledger ORDER BY seq DESC LIMIT ?", (limit,))
            out = []
            for r in rows.fetchall():
                d = dict(r)
                d["payload"] = json.loads(d["payload"])
                out.append(d)
            return out

    def head(self) -> dict[str, Any] | None:
        with self._conn() as c:
            r = c.execute("SELECT seq, hash, ts FROM ledger ORDER BY seq DESC LIMIT 1").fetchone()
            return dict(r) if r else None

    def verify(self) -> dict[str, Any]:
        """Recompute the whole chain. Returns ok flag, count, head, and first broken seq."""
        prev, count = GENESIS, 0
        with self._conn() as c:
            for r in c.execute("SELECT * FROM ledger ORDER BY seq ASC"):
                d = dict(r)
                count += 1
                if d["prev_hash"] != prev:
                    return {"ok": False, "entries": count, "first_bad_seq": d["seq"], "reason": "broken link (row deleted or reordered)"}
                if entry_hash(d) != d["hash"]:
                    return {"ok": False, "entries": count, "first_bad_seq": d["seq"], "reason": "content altered"}
                prev = d["hash"]
        return {"ok": True, "entries": count, "head_hash": prev if count else None, "first_bad_seq": None, "reason": None}

    # ---------------------------------------------------------------- cases
    def save_case(self, case_id: str, case_ref: str, crime_type: str, title: str | None,
                  kb_hash: str, input_obj: dict[str, Any], result_obj: dict[str, Any], result_sha: str) -> None:
        now = utcnow()
        with self._conn() as c:
            c.execute(
                "INSERT INTO cases(case_id, case_ref, crime_type, title, created_at, updated_at, kb_hash, input_json, result_json, result_sha256) "
                "VALUES(?,?,?,?,?,?,?,?,?,?) ON CONFLICT(case_id) DO UPDATE SET "
                "updated_at=excluded.updated_at, kb_hash=excluded.kb_hash, input_json=excluded.input_json, "
                "result_json=excluded.result_json, result_sha256=excluded.result_sha256, title=excluded.title",
                (case_id, case_ref, crime_type, title, now, now, kb_hash, canonical(input_obj), canonical(result_obj), result_sha),
            )

    def get_case(self, case_id: str) -> dict[str, Any] | None:
        with self._conn() as c:
            r = c.execute("SELECT * FROM cases WHERE case_id=?", (case_id,)).fetchone()
        if not r:
            return None
        d = dict(r)
        d["input"] = json.loads(d.pop("input_json"))
        d["result"] = json.loads(d.pop("result_json"))
        return d


    def save_ai(self, case_id: str, ai_obj: dict[str, Any]) -> None:
        """Persist the AI-control envelope separately from the signed triage result.

        This keeps model diagnostics/provenance visible in the UI without changing
        the deterministic result hash used by the custody ledger.
        """
        with self._conn() as c:
            c.execute(
                "INSERT INTO case_ai(case_id, updated_at, ai_json) VALUES(?,?,?) "
                "ON CONFLICT(case_id) DO UPDATE SET updated_at=excluded.updated_at, ai_json=excluded.ai_json",
                (case_id, utcnow(), canonical(ai_obj)),
            )

    def get_ai(self, case_id: str) -> dict[str, Any] | None:
        with self._conn() as c:
            r = c.execute("SELECT ai_json FROM case_ai WHERE case_id=?", (case_id,)).fetchone()
        return json.loads(r["ai_json"]) if r else None

    def list_cases(self) -> list[dict[str, Any]]:
        with self._conn() as c:
            rows = c.execute(
                "SELECT case_id, case_ref, crime_type, title, created_at, updated_at, result_json FROM cases ORDER BY updated_at DESC"
            ).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            res = json.loads(d.pop("result_json"))
            d["counts"] = res.get("counts", {})
            d["value_retained"] = res.get("schedule", {}).get("recommended", {}).get("value_retained")
            out.append(d)
        return out

    def verify_case(self, case_id: str) -> dict[str, Any]:
        """Check that the stored result still matches the SHA-256 recorded in the ledger."""
        case = self.get_case(case_id)
        if not case:
            return {"ok": False, "reason": "unknown case"}
        stored = dict(case["result"])
        claimed = stored.pop("result_sha256", "")
        recomputed = sha256_text(canonical(stored))
        recorded = [e["payload"].get("result_sha256") for e in self.ledger(case_id) if e["action"] in ("triage", "retriage")]
        return {
            "ok": recomputed == claimed and claimed in recorded,
            "result_sha256": recomputed,
            "matches_stored": recomputed == claimed,
            "recorded_in_ledger": claimed in recorded,
        }
