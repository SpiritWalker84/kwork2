"""Kwork IT (c=11) monitor: pages 1-2, diff, Telegram alert."""

from __future__ import annotations

import html
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

MIN_STAR_PRICE = 5000
MIN_SOFT_PRICE = 10000

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

NEGATIVE_KEYWORDS = (
    "tilda",
    "тильд",
    "wordpress",
    "вордпресс",
    "elementor",
    " ios",
    "ios ",
    "android",
    "swift",
    "kotlin",
    "flutter",
    " java",
    "java ",
    "typescript",
    "javascript",
    " react",
    " vue",
    "laravel",
    "лендинг",
    "landing",
    "копия сайта",
    "копию сайта",
    " figma",
    "верстк",
    "верстка",
    "unity",
    "webgl",
    " seo",
    "битрикс",
    "bitrix",
    "modx",
    "woocommerce",
    "инфографик",
    "дизайн сайта",
    "сверстать",
)

STRONG_KEYWORDS = (
    "telegram",
    "телеграм",
    "тг-бот",
    "тг бот",
    "telegram-бот",
    "чат-бот",
    "aiogram",
    "python",
    "openai",
    "chatgpt",
    "gpt",
    "rag",
    "llm",
    "n8n",
    "prompt",
    "промпт",
    "fastapi",
    "mini app",
    "mini-app",
    "ии-бот",
    "ii-бот",
)

SOFT_KEYWORDS = (
    "парсер",
    "парсинг",
    "мониторинг",
    "автоматиза",
    "docker",
    "postgresql",
    "backend",
    "бекенд",
    "api",
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


def is_negative(want: dict) -> bool:
    text = want_text(want)
    if is_blocked(want):
        return True
    return any(keyword in text for keyword in NEGATIVE_KEYWORDS)


def is_star_relevant(want: dict) -> bool:
    if is_negative(want):
        return False

    text = want_text(want)
    price = float(want.get("priceLimit") or 0)
    if price < MIN_STAR_PRICE:
        return False

    if any(keyword in text for keyword in STRONG_KEYWORDS):
        return True
    if price >= MIN_SOFT_PRICE and any(keyword in text for keyword in SOFT_KEYWORDS):
        return True
    return False


def star_sort_key(want: dict) -> tuple[int, float]:
    text = want_text(want)
    strong = sum(1 for keyword in STRONG_KEYWORDS if keyword in text)
    return (strong, float(want.get("priceLimit") or 0))


def validate_config() -> tuple[str, str]:
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip().strip('"').strip("'")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "").strip().strip('"').strip("'")
    if not token:
        raise RuntimeError(
            "Не задан TELEGRAM_BOT_TOKEN. Добавьте Secret в GitHub: "
            "Settings → Secrets → Actions"
        )
    if not chat_id:
        raise RuntimeError(
            "Не задан TELEGRAM_CHAT_ID. Напишите боту /start и возьмите id "
            "через @getmyid_bot"
        )
    if not re.fullmatch(r"\d+:[A-Za-z0-9_-]+", token):
        raise RuntimeError(
            "TELEGRAM_BOT_TOKEN похож на неверный формат. "
            "Скопируйте token из @BotFather целиком, без кавычек и пробелов."
        )
    return token, chat_id


def check_telegram_bot(token: str) -> str:
    response = requests.get(
        f"https://api.telegram.org/bot{token}/getMe",
        timeout=30,
    )
    try:
        data = response.json()
    except ValueError as exc:
        raise RuntimeError(
            f"Telegram getMe вернул не-JSON ({response.status_code})"
        ) from exc
    if not data.get("ok"):
        description = data.get("description", "unknown error")
        raise RuntimeError(
            f"Неверный TELEGRAM_BOT_TOKEN: {description}. "
            "Создайте token заново в @BotFather и обновите Secret."
        )
    username = data["result"]["username"]
    print(f"telegram bot ok: @{username}")
    return username


def escape_html(text: str) -> str:
    return html.escape(text, quote=False)


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
    title = escape_html(want.get("name", "").strip())
    prefix = "⭐ " if mark_relevant else "• "
    return (
        f'{prefix}<a href="https://kwork.ru/projects/{want_id}">{title}</a>\n'
        f"{price:,} ₽".replace(",", " ")
    )


def build_message(projects: list[dict], *, total: int, new_projects: list[dict]) -> str | None:
    now = datetime.now(ZoneInfo("Europe/Moscow")).strftime("%d.%m.%Y %H:%M")
    star_new = sorted(
        [want for want in new_projects if is_star_relevant(want)],
        key=star_sort_key,
        reverse=True,
    )

    if not star_new:
        return None

    lines = [
        f"<b>Kwork IT</b> · {now} (МСК)",
        f"Всего в категории: {total}",
        f"<b>Новые ⭐ ({len(star_new)}):</b>",
        "",
    ]
    for want in star_new[:8]:
        lines.append(format_project(want, mark_relevant=True))

    return "\n".join(lines)


def build_bootstrap_message(projects: list[dict], *, total: int) -> str:
    now = datetime.now(ZoneInfo("Europe/Moscow")).strftime("%d.%m.%Y %H:%M")
    relevant = sorted(
        [want for want in projects if is_star_relevant(want)],
        key=star_sort_key,
        reverse=True,
    )
    lines = [
        f"<b>Kwork мониторинг запущен</b> · {now} (МСК)",
        f"Отслеживаю стр. 1–2, сейчас проектов: {len(projects)} (в категории {total}).",
        "Фильтр: Python / Telegram / AI / n8n / парсинг от 10k.",
        "Дальше — только <b>новые ⭐</b>.",
        "",
    ]
    if relevant:
        lines.append(f"<b>Сейчас ⭐ ({len(relevant)}):</b>")
        for want in relevant[:10]:
            lines.append(format_project(want, mark_relevant=True))
    else:
        lines.append("⭐ на первых двух страницах сейчас нет.")
    return "\n".join(lines)


def send_telegram(text: str) -> None:
    token, chat_id = validate_config()
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
        payload = {
            "chat_id": chat_id,
            "text": chunk,
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        }
        response = requests.post(url, json=payload, timeout=30)
        try:
            data = response.json()
        except ValueError as exc:
            raise RuntimeError(
                f"Telegram вернул не-JSON ({response.status_code}): {response.text[:300]}"
            ) from exc

        if not response.ok or not data.get("ok"):
            description = data.get("description", response.text[:300])
            hint = ""
            lowered = description.lower()
            if response.status_code == 403 or "can't initiate conversation" in lowered:
                hint = (
                    " Напишите боту /start в личке Telegram. "
                    "TELEGRAM_CHAT_ID = ваш Id (из @getmyid_bot), не id бота."
                )
            elif "blocked" in lowered:
                hint = " Разблокируйте бота в Telegram."
            elif "chat not found" in lowered:
                hint = " Напишите боту /start и проверьте TELEGRAM_CHAT_ID."
            elif "can't parse entities" in lowered:
                hint = " Ошибка HTML в тексте сообщения."
            elif response.status_code == 401 or "unauthorized" in lowered:
                hint = " Проверьте TELEGRAM_BOT_TOKEN в Secrets."
            raise RuntimeError(f"Telegram API ({response.status_code}): {description}.{hint}")

        print("telegram chunk sent")


def main() -> int:
    token, _chat_id = validate_config()
    check_telegram_bot(token)
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
        print(f"sent {len([w for w in new_projects if is_star_relevant(w)])} star projects")
    else:
        print("no star projects")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise
