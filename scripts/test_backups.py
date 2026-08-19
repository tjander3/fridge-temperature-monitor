import io
import json
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

import backup_database
import setup_backups
import sqlite_dump


class SqliteDumpTests(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.directory = Path(self.temporary_directory.name)
        self.source = self.directory / "source.db"
        with closing(sqlite3.connect(self.source)) as connection:
            connection.executescript(
                """
                CREATE TABLE readings (
                    id INTEGER PRIMARY KEY,
                    observed_at TEXT NOT NULL,
                    temperature_f REAL NOT NULL
                );
                CREATE INDEX readings_time_idx ON readings(observed_at);
                INSERT INTO readings VALUES (1, '2026-08-19T12:00:00Z', -11.0);
                CREATE TABLE settings (name TEXT PRIMARY KEY, value TEXT);
                INSERT INTO settings VALUES ('profile', 'freezer');
                """
            )
            connection.commit()

    def tearDown(self):
        self.temporary_directory.cleanup()

    def test_dump_restores_schema_data_and_integrity(self):
        output = io.StringIO()
        sqlite_dump.write_sql_dump(self.source, output)
        dump = self.directory / "backup.sql"
        dump.write_text(output.getvalue(), encoding="utf-8")

        result = sqlite_dump.restore_sql_dump(dump, self.directory / "restored.db")

        self.assertEqual(result["integrity_check"], "ok")
        self.assertEqual(result["table_row_counts"], {"readings": 1, "settings": 1})
        self.assertIn("CREATE TABLE readings", output.getvalue())
        self.assertIn("CREATE INDEX readings_time_idx", output.getvalue())

    def test_restore_refuses_to_replace_existing_database(self):
        dump = self.directory / "backup.sql"
        with dump.open("w", encoding="utf-8") as output:
            sqlite_dump.write_sql_dump(self.source, output)

        with self.assertRaises(FileExistsError):
            sqlite_dump.restore_sql_dump(dump, self.source)

    def test_manifest_records_hash_size_and_counts(self):
        dump = self.directory / "backup.sql"
        dump.write_text("BEGIN TRANSACTION;\nCOMMIT;\n", encoding="utf-8")
        validation = {"integrity_check": "ok", "table_row_counts": {"readings": 1}}

        manifest = backup_database.build_manifest(dump, validation)

        self.assertEqual(manifest["dump_size_bytes"], dump.stat().st_size)
        self.assertEqual(len(manifest["dump_sha256"]), 64)
        self.assertEqual(manifest["table_row_counts"], {"readings": 1})
        json.dumps(manifest)


class ScheduleTests(unittest.TestCase):
    def test_task_xml_runs_python_weekly_and_when_available(self):
        xml = setup_backups.build_task_xml(
            user="DESKTOP\\user",
            day="SUN",
            time="03:00",
            python=Path("C:/Python/python.exe"),
            backup_script=Path("C:/monitor/scripts/backup_database.py"),
            backup_repository=Path("C:/backups/home-app-backups"),
            distribution="Ubuntu-Docker",
        )

        self.assertIn("<Sunday />", xml)
        self.assertIn("<WeeksInterval>1</WeeksInterval>", xml)
        self.assertIn("<StartWhenAvailable>true</StartWhenAvailable>", xml)
        self.assertIn("backup_database.py", xml)
        self.assertIn("--wsl-distribution Ubuntu-Docker", xml)


class GitHubSafetyTests(unittest.TestCase):
    def test_extracts_repository_from_supported_ssh_remotes(self):
        self.assertEqual(
            backup_database.repository_name_from_remote(
                "git@github.com:tjander3/home-app-backups.git"
            ),
            "tjander3/home-app-backups",
        )
        self.assertEqual(
            backup_database.repository_name_from_remote(
                "ssh://git@ssh.github.com:443/tjander3/home-app-backups.git"
            ),
            "tjander3/home-app-backups",
        )

    def test_rejects_non_github_remote(self):
        with self.assertRaises(backup_database.BackupError):
            backup_database.repository_name_from_remote("file:///tmp/backups.git")


if __name__ == "__main__":
    unittest.main()
