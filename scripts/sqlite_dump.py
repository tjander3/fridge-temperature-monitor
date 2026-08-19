"""Create and validate portable SQL dumps of SQLite databases."""

from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path
from typing import TextIO


def quote_identifier(name: str) -> str:
    """Return a safely quoted SQLite identifier."""

    return '"' + name.replace('"', '""') + '"'


def write_sql_dump(database_path: str | Path, output: TextIO) -> None:
    """Write a transactionally consistent SQL dump to *output*.

    The read transaction pins a single WAL snapshot for the full export. The
    integrity check runs against that same snapshot before any SQL is emitted.
    """

    database = Path(database_path)
    connection = sqlite3.connect(
        f"file:{database.as_posix()}?mode=ro", uri=True, timeout=30
    )
    try:
        connection.execute("BEGIN")
        integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
        if integrity != "ok":
            raise RuntimeError(f"SQLite integrity check failed: {integrity}")

        for statement in connection.iterdump():
            output.write(statement)
            output.write("\n")
    finally:
        connection.close()


def restore_sql_dump(
    dump_path: str | Path, database_path: str | Path, *, overwrite: bool = False
) -> dict[str, object]:
    """Restore *dump_path* and return integrity and per-table row counts."""

    dump = Path(dump_path)
    database = Path(database_path)
    if database.exists() and not overwrite:
        raise FileExistsError(f"restore target already exists: {database}")
    if database.exists():
        database.unlink()

    database.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(database)
    try:
        connection.executescript(dump.read_text(encoding="utf-8"))
        integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
        if integrity != "ok":
            raise RuntimeError(f"restored SQLite integrity check failed: {integrity}")

        tables = [
            row[0]
            for row in connection.execute(
                """
                SELECT name
                FROM sqlite_master
                WHERE type = 'table' AND name NOT LIKE 'sqlite_%'
                ORDER BY name
                """
            )
        ]
        counts = {
            table: connection.execute(
                f"SELECT COUNT(*) FROM {quote_identifier(table)}"
            ).fetchone()[0]
            for table in tables
        }
        return {"integrity_check": integrity, "table_row_counts": counts}
    except Exception:
        connection.close()
        database.unlink(missing_ok=True)
        raise
    finally:
        connection.close()


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Write a consistent SQLite SQL dump to standard output."
    )
    parser.add_argument("database", help="SQLite database path")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        write_sql_dump(args.database, sys.stdout)
    except Exception as error:  # pragma: no cover - exercised by the caller
        print(f"database export failed: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
