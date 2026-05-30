from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
import tomllib
from pathlib import Path


PROJECT_DIR = Path(__file__).resolve().parent
PYPROJECT_PATH = PROJECT_DIR / "pyproject.toml"
UV_LOCK_PATH = PROJECT_DIR / "uv.lock"
VERSION_RE = re.compile(r"^\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?$")
ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")


class Style:
    def __init__(self) -> None:
        enabled = sys.stdout.isatty() and os.environ.get("NO_COLOR") is None
        self.reset = "\033[0m" if enabled else ""
        self.dim = "\033[2m" if enabled else ""
        self.bold = "\033[1m" if enabled else ""
        self.cyan = "\033[36m" if enabled else ""
        self.blue = "\033[34m" if enabled else ""
        self.green = "\033[32m" if enabled else ""
        self.yellow = "\033[33m" if enabled else ""
        self.red = "\033[31m" if enabled else ""


S = Style()


def configure_stdio() -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


def strip_ansi(text: str) -> str:
    return ANSI_RE.sub("", text)


def display_width(text: str) -> int:
    return len(strip_ansi(text))


def fit(text: str, width: int) -> str:
    return text + " " * max(0, width - display_width(text))


def run_git(args: list[str], *, capture: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=PROJECT_DIR,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=capture,
        check=False,
    )


def require_git(args: list[str]) -> str:
    result = run_git(args)
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()
        raise RuntimeError(detail or f"git {' '.join(args)} failed")
    return result.stdout.strip()


def read_project() -> tuple[str, str]:
    with PYPROJECT_PATH.open("rb") as f:
        project = tomllib.load(f).get("project", {})
    name = project.get("name") or PROJECT_DIR.name
    version = project.get("version")
    if not version:
        raise RuntimeError("pyproject.toml 缺少 [project].version")
    return str(name), str(version)


def next_patch(version: str) -> str:
    match = re.match(r"^(\d+)\.(\d+)\.(\d+)$", version)
    if not match:
        return version
    major, minor, patch = (int(part) for part in match.groups())
    return f"{major}.{minor}.{patch + 1}"


def ensure_clean_worktree() -> None:
    status = require_git(["status", "--porcelain"])
    if status:
        raise RuntimeError(
            "工作区不干净。发版前请先提交或处理现有改动，避免把无关内容混入 release commit。"
        )


def tag_exists(tag: str) -> bool:
    result = run_git(["rev-parse", "--verify", "--quiet", f"refs/tags/{tag}"])
    return result.returncode == 0


def replace_version_line(path: Path, version: str) -> None:
    text = path.read_text(encoding="utf-8")
    new_text, count = re.subn(
        r'(?m)^version\s*=\s*"[^"]+"',
        f'version = "{version}"',
        text,
        count=1,
    )
    if count != 1:
        raise RuntimeError(f"找不到 version 字段: {path.name}")
    path.write_text(new_text, encoding="utf-8", newline="")


def sync_uv_lock(project_name: str, version: str) -> bool:
    if not UV_LOCK_PATH.exists():
        return False

    lines = UV_LOCK_PATH.read_text(encoding="utf-8").splitlines(keepends=True)
    in_package = False
    is_target = False

    for index, line in enumerate(lines):
        stripped = line.strip()
        if stripped == "[[package]]":
            in_package = True
            is_target = False
            continue
        if in_package and stripped.startswith("[") and stripped != "[[package]]":
            in_package = False
            is_target = False
            continue
        if in_package and stripped == f'name = "{project_name}"':
            is_target = True
            continue
        if in_package and is_target and stripped.startswith("version = "):
            newline = "\n" if line.endswith("\n") else ""
            lines[index] = f'version = "{version}"{newline}'
            UV_LOCK_PATH.write_text("".join(lines), encoding="utf-8", newline="")
            return True

    raise RuntimeError(f"uv.lock 中找不到项目版本: {project_name}")


def prompt_value(label: str, default: str = "") -> str:
    suffix = f" {S.dim}[{default}]{S.reset}" if default else ""
    value = input(f"{S.cyan}{label}{S.reset}{suffix}  ").strip()
    return value or default


def prompt_yes_no(label: str, default: bool = True) -> bool:
    hint = "Y/n" if default else "y/N"
    while True:
        answer = input(f"{S.cyan}{label}{S.reset} {S.dim}[{hint}]{S.reset}  ").strip().lower()
        if not answer:
            return default
        if answer in {"y", "yes"}:
            return True
        if answer in {"n", "no"}:
            return False
        print(f"{S.yellow}请输入 y 或 n。{S.reset}")


def panel(title: str, rows: list[tuple[str, str]], footer: str | None = None) -> None:
    label_width = max([len(label) for label, _ in rows] + [0])
    row_texts = [f"{S.dim}{label.rjust(label_width)}{S.reset}  {value}" for label, value in rows]
    content_width = max([display_width(title), *(display_width(row) for row in row_texts), display_width(footer or "")])
    width = max(46, content_width + 4)

    print(f"{S.blue}╭─{S.reset} {S.bold}{title}{S.reset} {S.blue}{'─' * max(0, width - display_width(title) - 4)}╮{S.reset}")
    for row in row_texts:
        print(f"{S.blue}│{S.reset} {fit(row, width - 2)} {S.blue}│{S.reset}")
    if footer:
        print(f"{S.blue}├{'─' * width}┤{S.reset}")
        print(f"{S.blue}│{S.reset} {fit(footer, width - 2)} {S.blue}│{S.reset}")
    print(f"{S.blue}╰{'─' * width}╯{S.reset}")


def print_step(label: str, ok: bool = True) -> None:
    state = f"{S.green}done{S.reset}" if ok else f"{S.red}fail{S.reset}"
    print(f"  {S.dim}{label:<28}{S.reset} {state}")


def update_versions(project_name: str, version: str) -> list[str]:
    changed = ["pyproject.toml"]
    replace_version_line(PYPROJECT_PATH, version)
    if sync_uv_lock(project_name, version):
        changed.append("uv.lock")
    return changed


def create_commit_and_tag(files: list[str], version: str, message: str) -> None:
    require_git(["add", "--", *files])
    require_git(["commit", "-m", message])
    require_git(["tag", "-a", f"v{version}", "-m", f"Release v{version}"])


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Create a release commit and tag.")
    parser.add_argument("version", nargs="?", help="new version, for example: 1.5.0")
    parser.add_argument("-m", "--message", help="release commit message")
    parser.add_argument("-y", "--yes", action="store_true", help="skip final confirmation")
    return parser.parse_args()


def main() -> int:
    configure_stdio()
    args = parse_args()

    try:
        project_name, current_version = read_project()
        branch = require_git(["branch", "--show-current"]) or "detached"
        ensure_clean_worktree()
    except Exception as exc:
        print(f"{S.red}Release blocked{S.reset}")
        print(f"{S.dim}{exc}{S.reset}")
        return 1

    suggested = next_patch(current_version)
    version = args.version or prompt_value("Next version", suggested)
    if not VERSION_RE.match(version):
        print(f"{S.red}版本号格式无效:{S.reset} {version}")
        print(f"{S.dim}示例: 1.5.0, 1.5.0-beta.1{S.reset}")
        return 1
    if version == current_version:
        print(f"{S.red}新版本不能等于当前版本。{S.reset}")
        return 1

    tag = f"v{version}"
    if tag_exists(tag):
        print(f"{S.red}tag 已存在:{S.reset} {tag}")
        return 1

    default_message = f"chore: 发布 v{version}"
    message = args.message or prompt_value("Commit message", default_message)

    print()
    panel(
        "cc-model-switch Release",
        [
            ("Project", project_name),
            ("Branch", branch),
            ("Current", f"v{current_version}"),
            ("Next", f"{S.green}v{version}{S.reset}"),
            ("Commit", message),
            ("Tag", tag),
        ],
        footer="No syntax check. No build. Version source: pyproject.toml.",
    )
    print()

    if not args.yes and not prompt_yes_no("Create this release?", True):
        print(f"{S.dim}已取消，未修改任何文件。{S.reset}")
        return 0

    try:
        changed = update_versions(project_name, version)
        print_step("Update pyproject.toml")
        if "uv.lock" in changed:
            print_step("Sync uv.lock")
        create_commit_and_tag(changed, version, message)
        print_step("Create release commit")
        print_step(f"Create tag {tag}")
    except Exception as exc:
        print(f"\n{S.red}Release failed{S.reset}")
        print(f"{S.dim}{exc}{S.reset}")
        print(f"{S.dim}版本文件可能已修改，请检查 git status。{S.reset}")
        return 1

    print()
    panel(
        "Release Ready",
        [
            ("Version", f"v{version}"),
            ("Commit", require_git(["rev-parse", "--short", "HEAD"])),
            ("Push", f"git push origin {branch} --follow-tags"),
        ],
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
