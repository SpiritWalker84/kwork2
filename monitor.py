"""Kwork IT (c=11) monitor: pages 1-2, diff, Telegram alert."""

from __future__ import annotations

import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import requests

KWORK_CATEGORY = 11
PAGES = (1, 2)
USER_AGENT = "Mozilla/5.0 (compatible; KworkMonitor/1.0)"
SNAPSHOT_PATH = Path(os.environ.get("KWORK_SNAPSHOT", ".snapshot.json"))

NEGATIVE_PATTERNS = (
    r"массов(ый|ого|ые)\s+инвайт",
    r"инвайт.*вконтакт",
    r"автокоммент",
    r"размещени.*объявлен",
    r"просмотр.*(ютуб|youtube|дзен|рутуб)",
    r"монетизац",
    r"принудительн",
    r"регистратор каналов",
)

POSITIVE_KEYWORDS = (
    "telegram",
    "телеграм",
    "тг-бот",
    "тг бот",
    "telegram-бот",
    "чат-бот",
    "aiogram",
    "python",
    "openai",
    "gpt",
    "rag",
    "n8n",
    "парсер",
    "парсинг",
    "мониторинг",
    "fastapi",
    "docker",
    "postgresql",
    "ии-",
    " ai ",
    "llm",
    "автоматиза",
    "mini app",
    "mini-app",
)


def fetch_page(page: int) -> dict:
    url = f"https://kwork.ru/projects?c={KWORK_CATEGORY}&page={page}"
    response = requests.get(
        url,
        headers={"User-Agent": USER_AGENT},
        timeout=60,
    )
    response.raise_for_status()
    html = response.text
    marker = "window.stateData="
    start = html.find(marker)
    if start < 0:
        raise RuntimeError(f"stateData not found on page {page}")

    start += len(marker)
    depth = 0
    for index, char in enumerate(html[start:], start=start):
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return json.loads(html[start : index + 1])
    raise RuntimeError(f"failed to parse stateData on page {page}")


def load_snapshot() -> dict:
    if not SNAPSHOT_PATH.exists():
        return {"initialized": False, "known_ids": []}
    data = json.loads(SNAPSHOT_PATH.read_text(encoding="utf-8"))
    data.setdefault("initialized", False)
    data.setdefault("known_ids", [])
    return data


def save_snapshot(snapshot: dict) -> None:
    SNAPSHOT_PATH.parent.mkdir(parents=True, exist_ok=True)
    SNAPSHOT_PATH.write_text(
        json.dumps(snapshot, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def want_text(want: dict) -> str:
    return f"{want.get('name', '')} {want.get('description', '')}".lower()


def is_blocked(want: dict) -> bool:
    text = want_text(want)
    return any(re.search(pattern, text) for pattern in NEGATIVE_PATTERNS)


def relevance_score(want: dict) -> int:
    if is_blocked(want):
        return -1
    text = want_text(want)
    score = sum(1 for keyword in POSITIVE_KEYWORDS if keyword in text)
    price = float(want.get("priceLimit") or 0)
    if price >= 10000:
        score += 2
    elif price >= 5000:
        score += 1
    return score


def fetch_projects() -> tuple[list[dict], int]:
    projects: list[dict] = []
    total = 0
    seen: set[int] = set()

    for page in PAGES:
        data = fetch_page(page)
        wants = data.get("wants", [])
        pagination = data.get("wantsListData", {}).get("pagination", {})
        total = int(pagination.get("total") or total)
        for want in wants:
            want_id = int(want["id"])
            if want_id in seen:
                continue
            seen.add(want_id)
            projects.append(want)
    return projects, total


def format_project(want: dict, *, mark_relevant: bool) -> str:
    want_id = want["id"]
    price = int(float(want.get("priceLimit") or 0))
    title = want.get("name", "").strip()
    prefix = "⭐ " if mark_relevant else "• "
    return f'{prefix}<a href="https://kwork.ru/projects/{want_id}">{title}</a>\n{price:,} ₽'.replace(",", " ")


def build_message(projects: list[dict], *, total: int, new_projects: list[dict]) -> str | None:
    now = datetime.now(ZoneInfo("Europe/Moscow")).strftime("%d.%m.%Y %H:%M")
    relevant_new = [want for want in new_projects if relevance_score(want) >= 2]

    if not new_projects:
        return None

    lines = [f"<b>Kwork IT</b> · {now} (МСК)", f"Всего в категории: {total}", ""]

    if relevant_new:
        lines.append(f"<b>Релевантные новые ({len(relevant_new)}):</b>")
        for want in relevant_new[:8]:
            lines.append(format_project(want, mark_relevant=True))
        lines.append("")

    other_new = [want for want in new_projects if want not in relevant_new][:6]
    if other_new:
        lines.append(f"<b>Остальные новые ({len(new_projects) - len(relevant_new)}):</b>")
        for want in other_new:
            lines.append(format_project(want, mark_relevant=False))

    return "\n".join(lines)


def build_bootstrap_message(projects: list[dict], *, total: int) -> str:
    now = datetime.now(ZoneInfo("Europe/Moscow")).strftime("%d.%m.%Y %H:%M")
    relevant = [want for want in projects if relevance_score(want) >= 2]
    lines = [
        f"<b>Kwork мониторинг запущен</b> · {now} (МСК)",
        f"Отслеживаю стр. 1–2, сейчас проектов: {len(projects)} (в категории {total}).",
        "Дальше буду присылать только <b>новые</b> заказы.",
        "",
    ]
    if relevant:
        lines.append(f"<b>Сейчас релевантные ({len(relevant)}):</b>")
        for want in relevant[:10]:
            lines.append(format_project(want, mark_relevant=True))
    else:
        lines.append("Релевантных на первых двух страницах сейчас нет.")
    return "\n".join(lines)


def send_telegram(text: str) -> None:
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
    if not token or not chat_id:
        raise RuntimeError("Set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID")

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    chunks: list[str] = []
    if len(text) <= 4000:
        chunks = [text]
    else:
        current = ""
        for line in text.split("\n"):
            candidate = f"{current}\n{line}".strip()
            if len(candidate) > 4000:
                chunks.append(current)
                current = line
            else:
                current = candidate
        if current:
            chunks.append(current)

    for chunk in chunks:
        response = requests.post(
            url,
            json={
                "chat_id": chat_id,
                "text": chunk,
                "parse_mode": "HTML",
                "disable_web_page_preview": True,
            },
            timeout=30,
        )
        response.raise_for_status()
        payload = response.json()
        if not payload.get("ok"):
            raise RuntimeError(f"Telegram error: {payload}")


def main() -> int:
    snapshot = load_snapshot()
    known_ids = {int(item) for item in snapshot.get("known_ids", [])}
    projects, total = fetch_projects()
    current_ids = {int(want["id"]) for want in projects}

    if not snapshot.get("initialized"):
        message = build_bootstrap_message(projects, total=total)
        send_telegram(message)
        snapshot = {
            "initialized": True,
            "known_ids": sorted(known_ids | current_ids),
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        save_snapshot(snapshot)
        print(f"bootstrap sent, tracking {len(snapshot['known_ids'])} ids")
        return 0

    new_projects = [want for want in projects if int(want["id"]) not in known_ids]
    message = build_message(projects, total=total, new_projects=new_projects)
    snapshot["known_ids"] = sorted(known_ids | current_ids)
    snapshot["updated_at"] = datetime.now(timezone.utc).isoformat()
    save_snapshot(snapshot)

    if message:
        send_telegram(message)
        print(f"sent {len(new_projects)} new projects")
    else:
        print("no new projects")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise
