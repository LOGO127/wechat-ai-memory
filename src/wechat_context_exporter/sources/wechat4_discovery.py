from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from .base import SourceError


@dataclass(frozen=True, slots=True)
class WeChat4Account:
    account_dir: Path

    @property
    def id(self) -> str:
        return self.account_dir.name

    @property
    def db_dir(self) -> Path:
        return self.account_dir / "db_storage"

    @property
    def attachment_dir(self) -> Path:
        return self.account_dir / "msg" / "attach"


def discover_wechat4_accounts() -> list[WeChat4Account]:
    roots = _candidate_xwechat_roots()
    accounts: list[WeChat4Account] = []
    seen: set[Path] = set()
    for root in roots:
        if not root.is_dir():
            continue
        try:
            children = list(root.iterdir())
        except OSError:
            continue
        for child in children:
            if not child.is_dir() or child.name.lower() == "all_users":
                continue
            db_dir = child / "db_storage"
            if (db_dir / "session" / "session.db").is_file() and child not in seen:
                accounts.append(WeChat4Account(child.resolve()))
                seen.add(child)
    return sorted(accounts, key=lambda account: account.account_dir.stat().st_mtime, reverse=True)


def select_wechat4_account(path: str | Path | None = None) -> WeChat4Account:
    if path is not None:
        candidate = Path(path).expanduser().resolve()
        if candidate.name.lower() == "db_storage":
            candidate = candidate.parent
        if candidate.name.lower() == "xwechat_files":
            matches = _accounts_under(candidate)
            if len(matches) == 1:
                return matches[0]
            if not matches:
                raise SourceError(f"No WeChat 4.x account found under {candidate}")
            raise SourceError("Multiple WeChat accounts found; choose the account directory")
        account = WeChat4Account(candidate)
        if not (account.db_dir / "session" / "session.db").is_file():
            raise SourceError(f"Not a WeChat 4.x account directory: {candidate}")
        return account

    accounts = discover_wechat4_accounts()
    if not accounts:
        raise SourceError("No local WeChat 4.x data directory was found")
    return accounts[0]


def _accounts_under(root: Path) -> list[WeChat4Account]:
    matches: list[WeChat4Account] = []
    try:
        children = list(root.iterdir())
    except OSError:
        return matches
    for child in children:
        if child.is_dir() and (child / "db_storage" / "session" / "session.db").is_file():
            matches.append(WeChat4Account(child.resolve()))
    return matches


def _candidate_xwechat_roots() -> list[Path]:
    candidates: list[Path] = []
    user_profile = Path(os.environ.get("USERPROFILE", str(Path.cwd())))
    candidates.extend(
        [
            user_profile / "Documents" / "xwechat_files",
            user_profile / "xwechat_files",
        ]
    )

    if os.name == "nt":
        for letter in "CDEFGHIJKLMNOPQRSTUVWXYZ":
            drive = Path(f"{letter}:/")
            if not drive.exists():
                continue
            candidates.append(drive / "xwechat_files")
            try:
                top_level = list(drive.iterdir())
            except OSError:
                continue
            for directory in top_level:
                if directory.is_dir():
                    candidates.append(directory / "xwechat_files")

    unique: list[Path] = []
    seen: set[str] = set()
    for candidate in candidates:
        key = str(candidate).casefold()
        if key not in seen:
            unique.append(candidate)
            seen.add(key)
    return unique

