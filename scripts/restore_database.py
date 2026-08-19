"""Restore or verify a fridge monitor SQLite SQL dump."""

from __future__ import annotations

import argparse
import json
import tempfile
from pathlib import Path

from sqlite_dump import restore_sql_dump


DEFAULT_BACKUP_REPOSITORY = (
    Path(__file__).resolve().parents[2] / "home-app-backups"
)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Validate a backup or restore it to a new SQLite database file."
    )
    parser.add_argument(
        "--dump",
        type=Path,
        default=DEFAULT_BACKUP_REPOSITORY / "fridge-monitor.sql",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="New SQLite database to create; omit to perform a temporary test restore",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Replace an existing --output file",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        if args.output:
            result = restore_sql_dump(args.dump, args.output, overwrite=args.force)
            destination = str(args.output.resolve())
        else:
            with tempfile.TemporaryDirectory(prefix="fridge-restore-test-") as directory:
                result = restore_sql_dump(args.dump, Path(directory) / "restored.db")
            destination = "temporary validation database"
        print(json.dumps({"restored_to": destination, **result}, indent=2))
    except Exception as error:
        print(f"restore failed: {error}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
