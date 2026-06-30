# Kwork IT monitor

Проверяет [биржу Kwork «Разработка и IT»](https://kwork.ru/projects?c=11) (стр. 1–2) **3 раза в день** и шлёт новые заказы в Telegram.

Расписание: **08:00, 14:00, 20:00 МСK** (GitHub Actions, компьютер можно не включать).

## 1. Telegram-бот

1. Напишите [@BotFather](https://t.me/BotFather) → `/newbot` → сохраните **token**.
2. Напишите боту любое сообщение.
3. Узнайте **chat_id**: [@getmyid_bot](https://t.me/getmyid_bot) или откройте  
   `https://api.telegram.org/bot<TOKEN>/getUpdates`

## 2. Репозиторий на GitHub

```powershell
cd c:\projects\zakaz1\kwork-monitor
git init
git add .
git commit -m "Add Kwork monitor"
```

Создайте репозиторий (уже есть): **https://github.com/SpiritWalker84/kwork2**

```powershell
cd c:\projects\zakaz1\kwork-monitor
git init
git add .
git commit -m "Add Kwork IT monitor with GitHub Actions"
git remote add origin https://github.com/SpiritWalker84/kwork2.git
git branch -M main
git push -u origin main
```

> Пушьте **только папку `kwork-monitor`**, не весь `zakaz1`.  
> Репозиторий [SpiritWalker84/kwork2](https://github.com/SpiritWalker84/kwork2) сейчас **public** — это нормально: token и chat_id только в GitHub Secrets, не в коде.

## 3. Secrets в GitHub

Repo → **Settings** → **Secrets and variables** → **Actions** → **New repository secret**:

| Secret | Значение |
|--------|----------|
| `TELEGRAM_BOT_TOKEN` | token от BotFather |
| `TELEGRAM_CHAT_ID` | ваш chat id |

## 4. Проверка

Actions → **Kwork IT monitor** → **Run workflow**.

Первый запуск: «мониторинг запущен» + текущие ⭐ (Python/TG/AI/n8n).  
Дальше — только **новые ⭐**. Сайты, Tilda, iOS, Java — отсеиваются.

Фильтр ⭐:
- **Сильные:** telegram, aiogram, python, openai, rag, n8n, fastapi, mini app
- **Мягкие** (от 10k): парсинг, мониторинг, автоматизация, API
- **Минус:** tilda, wordpress, ios, java, лендинг, копия сайта, figma, seo…

## Если workflow падает с exit code 1

**Предупреждение про Node.js 20** — это warning, не причина падения.

Частые причины:

| Ошибка в логе | Что сделать |
|---------------|-------------|
| `TELEGRAM_BOT_TOKEN не задан` | Settings → Secrets → добавить оба secret |
| `chat not found` | Напишите **вашему боту** `/start`, затем обновите `TELEGRAM_CHAT_ID` |
| `Unauthorized` / 401 | Неверный token от @BotFather |
| **403 Forbidden** | **Не нажали /start у бота** или указали **не тот chat_id** (нужен *ваш* Id, не id бота) |
| `can't parse entities` | Обновите код (исправлено экранирование HTML) |

В логе шага **Run monitor** смотрите строку `ERROR: ...` — там точная причина.

```powershell
cd c:\projects\zakaz1\kwork-monitor
pip install -r requirements.txt
$env:TELEGRAM_BOT_TOKEN="..."
$env:TELEGRAM_CHAT_ID="..."
python monitor.py
```

Удалите `.snapshot.json` перед повторным «первым» запуском.
