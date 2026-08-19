"""Create the private GitHub backup repository and weekly Windows task."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timedelta
from pathlib import Path
from xml.sax.saxutils import escape


DEFAULT_GITHUB_REPOSITORY = "tjander3/home-app-backups"
DEFAULT_BACKUP_REPOSITORY = (
    Path(__file__).resolve().parents[2] / "home-app-backups"
)
DEFAULT_TASK_NAME = "Fridge Temperature Monitor Weekly Database Backup"
DAY_NAMES = {
    "MON": "Monday",
    "TUE": "Tuesday",
    "WED": "Wednesday",
    "THU": "Thursday",
    "FRI": "Friday",
    "SAT": "Saturday",
    "SUN": "Sunday",
}


class SetupError(RuntimeError):
    """Raised when backup setup cannot be completed safely."""


def run(
    command: list[str],
    *,
    cwd: Path | None = None,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        command,
        cwd=cwd,
        text=True,
        capture_output=True,
        check=False,
    )
    if check and result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip() or "unknown error"
        raise SetupError(f"command failed ({command[0]}): {detail}")
    return result


def find_github_cli(explicit: Path | None = None) -> str:
    candidates = [
        explicit,
        Path(shutil.which("gh") or "") if shutil.which("gh") else None,
        Path(__file__).resolve().parents[2] / ".tools" / "gh" / "bin" / "gh.exe",
    ]
    for candidate in candidates:
        if candidate and candidate.is_file():
            return str(candidate.resolve())
    raise SetupError("GitHub CLI was not found")


def github_repository(gh: str, name: str) -> dict[str, str] | None:
    result = run(
        [gh, "repo", "view", name, "--json", "nameWithOwner,visibility,sshUrl"],
        check=False,
    )
    if result.returncode != 0:
        return None
    return json.loads(result.stdout)


def ensure_private_github_repository(gh: str, name: str) -> dict[str, str]:
    if run([gh, "auth", "status"], check=False).returncode != 0:
        raise SetupError(
            f"GitHub CLI is not authenticated. Run: {gh} auth login"
        )

    repository = github_repository(gh, name)
    if repository is None:
        run(
            [
                gh,
                "repo",
                "create",
                name,
                "--private",
                "--description",
                "Private automated backups for home applications",
            ]
        )
        repository = github_repository(gh, name)
    if repository is None:
        raise SetupError(f"GitHub repository could not be verified: {name}")
    if repository["visibility"].upper() != "PRIVATE":
        raise SetupError(
            f"refusing to back up to {name}: visibility is {repository['visibility']}"
        )
    return repository


def initialize_local_repository(path: Path, remote: dict[str, str]) -> None:
    if (path / ".git").is_dir():
        existing = run(["git", "remote", "get-url", "origin"], cwd=path).stdout.strip()
        if existing != remote["sshUrl"]:
            raise SetupError(
                f"existing backup repository uses unexpected origin: {existing}"
            )
        return
    if path.exists() and any(path.iterdir()):
        raise SetupError(f"backup directory is not empty: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    run(["git", "clone", remote["sshUrl"], str(path)])
    run(["git", "checkout", "-B", "main"], cwd=path)
    run(["git", "config", "user.name", "Tyler Anderson"], cwd=path)
    run(["git", "config", "user.email", "tjander22@gmail.com"], cwd=path)


def task_start_boundary(day: str, time: str) -> str:
    hour, minute = (int(part) for part in time.split(":"))
    target_weekday = list(DAY_NAMES).index(day)
    now = datetime.now()
    days_ahead = (target_weekday - now.weekday()) % 7
    candidate = (now + timedelta(days=days_ahead)).replace(
        hour=hour, minute=minute, second=0, microsecond=0
    )
    if candidate <= now:
        candidate += timedelta(days=7)
    return candidate.isoformat(timespec="seconds")


def quote_windows_argument(value: str | Path) -> str:
    return subprocess.list2cmdline([str(value)])


def build_task_xml(
    *,
    user: str,
    day: str,
    time: str,
    python: Path,
    backup_script: Path,
    backup_repository: Path,
    distribution: str,
) -> str:
    arguments = " ".join(
        [
            quote_windows_argument(backup_script),
            "--backup-repo",
            quote_windows_argument(backup_repository),
            "--wsl-distribution",
            quote_windows_argument(distribution),
        ]
    )
    values = {
        "user": escape(user),
        "boundary": task_start_boundary(day, time),
        "day": DAY_NAMES[day],
        "python": escape(str(python)),
        "arguments": escape(arguments),
        "working_directory": escape(str(backup_script.parent.parent)),
    }
    return f'''<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.4" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <RegistrationInfo>
    <Description>Creates, validates, commits, and pushes a weekly fridge monitor SQLite backup.</Description>
  </RegistrationInfo>
  <Triggers>
    <CalendarTrigger>
      <StartBoundary>{values["boundary"]}</StartBoundary>
      <Enabled>true</Enabled>
      <ScheduleByWeek>
        <DaysOfWeek><{values["day"]} /></DaysOfWeek>
        <WeeksInterval>1</WeeksInterval>
      </ScheduleByWeek>
    </CalendarTrigger>
  </Triggers>
  <Principals>
    <Principal id="Author">
      <UserId>{values["user"]}</UserId>
      <LogonType>InteractiveToken</LogonType>
      <RunLevel>LeastPrivilege</RunLevel>
    </Principal>
  </Principals>
  <Settings>
    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>
    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>
    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>
    <StartWhenAvailable>true</StartWhenAvailable>
    <RunOnlyIfNetworkAvailable>true</RunOnlyIfNetworkAvailable>
    <AllowHardTerminate>true</AllowHardTerminate>
    <Enabled>true</Enabled>
    <ExecutionTimeLimit>PT1H</ExecutionTimeLimit>
    <Priority>7</Priority>
  </Settings>
  <Actions Context="Author">
    <Exec>
      <Command>{values["python"]}</Command>
      <Arguments>{values["arguments"]}</Arguments>
      <WorkingDirectory>{values["working_directory"]}</WorkingDirectory>
    </Exec>
  </Actions>
</Task>
'''


def install_weekly_task(
    *,
    task_name: str,
    day: str,
    time: str,
    backup_repository: Path,
    distribution: str,
) -> None:
    if os.name != "nt":
        raise SetupError("Windows Task Scheduler setup is only available on Windows")
    user = run(["whoami"]).stdout.strip()
    xml = build_task_xml(
        user=user,
        day=day,
        time=time,
        python=Path(sys.executable).resolve(),
        backup_script=Path(__file__).with_name("backup_database.py").resolve(),
        backup_repository=backup_repository.resolve(),
        distribution=distribution,
    )
    with tempfile.TemporaryDirectory(prefix="fridge-backup-task-") as directory:
        xml_path = Path(directory) / "task.xml"
        xml_path.write_text(xml, encoding="utf-16")
        run(["schtasks", "/Create", "/TN", task_name, "/XML", str(xml_path), "/F"])
    run(["schtasks", "/Query", "/TN", task_name])


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Set up private weekly GitHub backups for the fridge monitor."
    )
    parser.add_argument("--github-repo", default=DEFAULT_GITHUB_REPOSITORY)
    parser.add_argument(
        "--backup-repo", type=Path, default=DEFAULT_BACKUP_REPOSITORY
    )
    parser.add_argument("--gh", type=Path)
    parser.add_argument("--wsl-distribution", default="Ubuntu-Docker")
    parser.add_argument("--day", choices=DAY_NAMES, default="SUN")
    parser.add_argument("--time", default="03:00")
    parser.add_argument("--task-name", default=DEFAULT_TASK_NAME)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        datetime.strptime(args.time, "%H:%M")
        gh = find_github_cli(args.gh)
        remote = ensure_private_github_repository(gh, args.github_repo)
        initialize_local_repository(args.backup_repo.resolve(), remote)

        backup_script = Path(__file__).with_name("backup_database.py")
        run(
            [
                sys.executable,
                str(backup_script),
                "--backup-repo",
                str(args.backup_repo.resolve()),
                "--wsl-distribution",
                args.wsl_distribution,
            ]
        )
        install_weekly_task(
            task_name=args.task_name,
            day=args.day,
            time=args.time,
            backup_repository=args.backup_repo,
            distribution=args.wsl_distribution,
        )
        print(f"Verified private repository: {remote['nameWithOwner']}")
        print(f"Created first backup in: {args.backup_repo.resolve()}")
        print(f"Installed weekly task: {args.task_name} ({args.day} {args.time})")
    except Exception as error:
        print(f"backup setup failed: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
