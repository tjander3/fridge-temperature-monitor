"""Back up the live Dockerized SQLite database to a private Git repository."""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import platform
import re
import shutil
import subprocess
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path

from sqlite_dump import restore_sql_dump


PROJECT_NAME = "fridge-temperature-monitor"
DEFAULT_DISTRIBUTION = "Ubuntu-Docker"
DEFAULT_DATABASE_PATH = "/data/fridge-monitor.db"
DEFAULT_BACKUP_REPOSITORY = (
    Path(__file__).resolve().parents[2] / "home-app-backups"
)
MANAGED_FILES = ("fridge-monitor.sql", "backup-manifest.json")
LOGGER = logging.getLogger("fridge-monitor-backup")


class BackupError(RuntimeError):
    """Raised when a backup cannot be completed safely."""


def run(
    command: list[str],
    *,
    cwd: Path | None = None,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    LOGGER.debug("running: %s", subprocess.list2cmdline(command))
    result = subprocess.run(
        command,
        cwd=cwd,
        text=True,
        capture_output=True,
        check=False,
    )
    if check and result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip() or "unknown error"
        raise BackupError(f"command failed ({command[0]}): {detail}")
    return result


def docker_command(distribution: str) -> list[str]:
    if platform.system() == "Windows":
        wsl = shutil.which("wsl.exe") or shutil.which("wsl")
        if not wsl:
            raise BackupError("wsl.exe was not found")
        return [wsl, "-d", distribution, "-u", "root", "--", "docker"]
    docker = shutil.which("docker")
    if not docker:
        raise BackupError("docker was not found")
    return [docker]


def find_dashboard_container(distribution: str) -> str:
    command = docker_command(distribution) + [
        "ps",
        "--filter",
        f"label=com.docker.compose.project={PROJECT_NAME}",
        "--filter",
        "label=com.docker.compose.service=dashboard",
        "--format",
        "{{.ID}}",
    ]
    containers = [line.strip() for line in run(command).stdout.splitlines() if line.strip()]
    if len(containers) != 1:
        raise BackupError(
            "expected one running dashboard container; start the monitor and try again"
        )
    return containers[0]


def export_from_container(
    destination: Path,
    *,
    distribution: str,
    database_path: str,
) -> None:
    container = find_dashboard_container(distribution)
    helper = Path(__file__).with_name("sqlite_dump.py")
    command = docker_command(distribution) + [
        "exec",
        "-i",
        container,
        "python",
        "-",
        database_path,
    ]
    LOGGER.info("Exporting %s from dashboard container %s", database_path, container)
    with helper.open("rb") as source, destination.open("wb") as output:
        result = subprocess.run(
            command,
            stdin=source,
            stdout=output,
            stderr=subprocess.PIPE,
            check=False,
        )
    if result.returncode != 0:
        destination.unlink(missing_ok=True)
        detail = result.stderr.decode("utf-8", errors="replace").strip()
        raise BackupError(f"Docker database export failed: {detail}")
    if destination.stat().st_size == 0:
        destination.unlink(missing_ok=True)
        raise BackupError("Docker database export produced an empty file")


def validate_dump(dump_path: Path) -> dict[str, object]:
    with tempfile.TemporaryDirectory(prefix="fridge-backup-verify-") as directory:
        restored = Path(directory) / "restored.db"
        return restore_sql_dump(dump_path, restored)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def build_manifest(dump_path: Path, validation: dict[str, object]) -> dict[str, object]:
    return {
        "created_at_utc": datetime.now(UTC).isoformat(),
        "database": DEFAULT_DATABASE_PATH,
        "dump_file": MANAGED_FILES[0],
        "dump_format": "SQLite SQL",
        "dump_sha256": sha256(dump_path),
        "dump_size_bytes": dump_path.stat().st_size,
        **validation,
    }


def ensure_backup_repository(repository: Path) -> None:
    if not (repository / ".git").is_dir():
        raise BackupError(
            f"backup repository is not initialized: {repository}; run setup_backups.py"
        )
    run(["git", "config", "user.name", "Tyler Anderson"], cwd=repository)
    run(["git", "config", "user.email", "tjander22@gmail.com"], cwd=repository)


def find_github_cli() -> str:
    candidates = [
        Path(shutil.which("gh")) if shutil.which("gh") else None,
        Path(__file__).resolve().parents[2] / ".tools" / "gh" / "bin" / "gh.exe",
    ]
    for candidate in candidates:
        if candidate and candidate.is_file():
            return str(candidate.resolve())
    raise BackupError("GitHub CLI was not found; refusing to push an unverified backup")


def repository_name_from_remote(remote: str) -> str:
    match = re.search(
        r"(?:github\.com|ssh\.github\.com)(?::\d+)?[/:]([^/]+/[^/]+?)(?:\.git)?$",
        remote,
    )
    if not match:
        raise BackupError(f"origin is not a recognized GitHub repository: {remote}")
    return match.group(1)


def verify_private_remote(repository: Path) -> str:
    remote = run(["git", "remote", "get-url", "origin"], cwd=repository).stdout.strip()
    name = repository_name_from_remote(remote)
    gh = find_github_cli()
    if run([gh, "auth", "status"], check=False).returncode != 0:
        raise BackupError("GitHub CLI authentication is unavailable; refusing to push")
    result = run([gh, "repo", "view", name, "--json", "nameWithOwner,visibility"])
    metadata = json.loads(result.stdout)
    if metadata["visibility"].upper() != "PRIVATE":
        raise BackupError(
            f"refusing to push database backup: {name} is {metadata['visibility']}"
        )
    return str(metadata["nameWithOwner"])


def refuse_unrelated_changes(repository: Path) -> None:
    status = run(["git", "status", "--porcelain"], cwd=repository).stdout.splitlines()
    managed = set(MANAGED_FILES)
    unrelated = []
    for line in status:
        path = line[3:].strip().strip('"') if len(line) > 3 else line
        if path not in managed:
            unrelated.append(line)
    if unrelated:
        raise BackupError(
            "backup repository has unrelated changes; resolve them first: "
            + "; ".join(unrelated)
        )


def commit_and_push(repository: Path, created_at: str) -> bool:
    run(["git", "add", "--", *MANAGED_FILES], cwd=repository)
    changed = run(
        ["git", "diff", "--cached", "--quiet", "--", *MANAGED_FILES],
        cwd=repository,
        check=False,
    )
    if changed.returncode == 0:
        LOGGER.info("The verified dump is unchanged; no commit is needed")
        return False
    if changed.returncode != 1:
        raise BackupError("git could not inspect the staged backup changes")

    date = created_at[:10]
    run(["git", "commit", "-m", f"Back up fridge monitor database ({date})"], cwd=repository)
    run(["git", "push", "origin", "HEAD"], cwd=repository)
    return True


def configure_logging(log_file: Path | None, verbose: bool) -> None:
    handlers: list[logging.Handler] = [logging.StreamHandler()]
    if log_file:
        log_file.parent.mkdir(parents=True, exist_ok=True)
        handlers.append(logging.FileHandler(log_file, encoding="utf-8"))
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        handlers=handlers,
    )


def backup(
    repository: Path,
    *,
    distribution: str,
    database_path: str,
) -> dict[str, object]:
    repository = repository.resolve()
    ensure_backup_repository(repository)
    refuse_unrelated_changes(repository)
    private_remote = verify_private_remote(repository)
    LOGGER.info("Verified private GitHub destination: %s", private_remote)

    temporary_dump = repository / f".{MANAGED_FILES[0]}.tmp"
    final_dump = repository / MANAGED_FILES[0]
    manifest_path = repository / MANAGED_FILES[1]
    temporary_dump.unlink(missing_ok=True)

    try:
        export_from_container(
            temporary_dump,
            distribution=distribution,
            database_path=database_path,
        )
        validation = validate_dump(temporary_dump)
        manifest = build_manifest(temporary_dump, validation)
        os.replace(temporary_dump, final_dump)
        manifest_path.write_text(
            json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        committed = commit_and_push(repository, str(manifest["created_at_utc"]))
        LOGGER.info(
            "Backup complete: %s bytes, %s",
            manifest["dump_size_bytes"],
            "committed and pushed" if committed else "no Git changes",
        )
        return manifest
    finally:
        temporary_dump.unlink(missing_ok=True)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Back up the live fridge monitor SQLite database to GitHub."
    )
    parser.add_argument(
        "--backup-repo", type=Path, default=DEFAULT_BACKUP_REPOSITORY
    )
    parser.add_argument("--wsl-distribution", default=DEFAULT_DISTRIBUTION)
    parser.add_argument("--database-path", default=DEFAULT_DATABASE_PATH)
    parser.add_argument(
        "--log-file",
        type=Path,
        default=Path(os.environ.get("LOCALAPPDATA", tempfile.gettempdir()))
        / "FridgeTemperatureMonitor"
        / "backup.log",
    )
    parser.add_argument("--verbose", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    configure_logging(args.log_file, args.verbose)
    try:
        backup(
            args.backup_repo,
            distribution=args.wsl_distribution,
            database_path=args.database_path,
        )
    except Exception as error:
        LOGGER.error("Backup failed: %s", error)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
