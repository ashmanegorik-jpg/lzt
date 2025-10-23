import os, json, asyncio, re, hashlib, time
from pathlib import Path

import httpx
from playwright.async_api import async_playwright

LZT_BASE = os.getenv("LZT_BASE", "https://zelenka.guru").rstrip("/")
ALERTS_URL = os.getenv("LZT_ALERTS_URL", f"{LZT_BASE}/account/alerts")
COOKIES_JSON = os.getenv("LZT_COOKIES_JSON", "")
BOT_EMAIL_ENDPOINT = os.getenv("BOT_EMAIL_ENDPOINT")  # https://<твой-бэк>/lolz/email
EMAIL_SECRET = os.getenv("EMAIL_SECRET", "")          # должен совпадать с CRON_SECRET на бэке
POLL_INTERVAL = int(os.getenv("POLL_INTERVAL", "25")) # сек между проверками
HEADLESS = os.getenv("HEADLESS", "1") == "1"

SEEN_FILE = Path("seen_alerts.txt")

PATTERN = re.compile(
    r'по вашей ссылке\s+["“][^"”]+["”].+?куплен аккаунт.+?за\s*\$?\s*([\d\.,]+)',
    re.IGNORECASE | re.DOTALL
)

def load_seen():
    if not SEEN_FILE.exists():
        return set()
    return set(x.strip() for x in SEEN_FILE.read_text(encoding="utf-8").splitlines() if x.strip())

def save_seen(seen: set):
    SEEN_FILE.write_text("\n".join(sorted(seen)), encoding="utf-8")

async def send_to_bot(text: str):
    if not BOT_EMAIL_ENDPOINT or not EMAIL_SECRET:
        print("BOT_EMAIL_ENDPOINT/EMAIL_SECRET not set — skip send")
        return
    async with httpx.AsyncClient(timeout=30.0) as client:
        r = await client.post(
            BOT_EMAIL_ENDPOINT,
            headers={"X-Secret": EMAIL_SECRET, "Content-Type": "application/json"},
            json={"text": text}
        )
        print("→ bot status:", r.status_code, r.text[:200])

async def grab_alert_texts(page) -> list[str]:
    # Берём весь текст страницы — этого достаточно для нужной фразы
    body_text = await page.inner_text("body")
    # Режем на “сообщения” по переводу строки, чтобы не ловить слишком длинные куски
    # и сразу фильтруем только те строки, где встречается ключевая часть
    candidates = []
    # Грубый способ — находить все матчи по PATTERN из всего текста
    for m in PATTERN.finditer(body_text):
        # Вырезаем побольше контекста вокруг найденной фразы:
        start = max(0, m.start() - 80)
        end   = min(len(body_text), m.end() + 80)
        chunk = body_text[start:end].strip()
        # Укоротим и нормализуем пробелы
        chunk = re.sub(r'\s+', ' ', chunk)
        candidates.append(chunk)
    return list(dict.fromkeys(candidates))  # uniq, порядок сохраняем

async def main():
    if not COOKIES_JSON:
        raise SystemExit("LZT_COOKIES_JSON is empty. Скопируй cookies JSON из Cookie-Editor в переменную окружения.")

    cookies = json.loads(COOKIES_JSON)
    seen = load_seen()
    print(f"Loaded {len(seen)} seen entries")

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=HEADLESS)
        context = await browser.new_context()
        # Добавляем cookies
        await context.add_cookies(cookies)
        page = await context.new_page()

        # Первый заход
        print("Open alerts:", ALERTS_URL)
        await page.goto(ALERTS_URL, wait_until="networkidle", timeout=60000)

        while True:
            try:
                # Обновляем страницу, чтобы подтянуть новые уведомления
                await page.reload(wait_until="networkidle", timeout=60000)
                texts = await grab_alert_texts(page)

                new_found = 0
                for t in texts:
                    # хеш по тексту для дедупликации
                    h = hashlib.sha1(t.encode("utf-8")).hexdigest()
                    if h in seen:
                        continue
                    if "по вашей ссылке" in t.lower() and "куплен аккаунт" in t.lower():
                        print("NEW ALERT:", t)
                        await send_to_bot(t)
                        seen.add(h)
                        new_found += 1

                if new_found:
                    save_seen(seen)
                    print(f"Saved seen, total {len(seen)}")
                else:
                    print("No new alerts")

            except Exception as e:
                print("Loop error:", e)

            await asyncio.sleep(POLL_INTERVAL)

if __name__ == "__main__":
    asyncio.run(main())
