#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Telegram автоматик технологик янгиликлар боти.

Иш тартиби:
  1. RSS манбалардан сўнгги янгиликларни йиғади.
  2. Аввал жойланганларини четлаб ўтади (такрорламайди).
  3. Claude орқали энг муҳим N тасини танлайди.
  4. Ҳар бирини ўзбекча (кирилл) Telegram пост шаклига айлантиради.
  5. Мақоланинг расми (og:image) билан каналга жойлайди.

VPS'да cron орқали кунига бир марта ишга туширилади.
"""

import os
import re
import json
import time
import html
import logging
from datetime import datetime, timezone, timedelta

import requests
import feedparser
from bs4 import BeautifulSoup
from dotenv import load_dotenv
from anthropic import Anthropic

# ---------------------------------------------------------------------------
# Созламалар
# ---------------------------------------------------------------------------
load_dotenv()

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "").strip()
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_CHANNEL = os.getenv("TELEGRAM_CHANNEL", "").strip()   # @kanal ёки -100... ID
CLAUDE_MODEL = os.getenv("CLAUDE_MODEL", "claude-haiku-4-5-20251001").strip()
POSTS_PER_DAY = int(os.getenv("POSTS_PER_DAY", "8"))
DELAY_BETWEEN_POSTS = int(os.getenv("DELAY_BETWEEN_POSTS", "60"))  # сония
LOOKBACK_HOURS = int(os.getenv("LOOKBACK_HOURS", "24"))
# Ҳар пост тагидаги обуна чақириғи (ихтиёрий)
CHANNEL_SIGNATURE = os.getenv("CHANNEL_SIGNATURE", "").strip()

STATE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "state.json")

# RSS манбалар — хоҳлаганингизча қўшинг/ўчиринг
SOURCES = {
    # --- IT / AI / технология ---
    "TechCrunch":        "https://techcrunch.com/feed/",
    "The Verge":         "https://www.theverge.com/rss/index.xml",
    "Ars Technica":      "https://feeds.arstechnica.com/arstechnica/index",
    "VentureBeat AI":    "https://venturebeat.com/category/ai/feed/",
    "Engadget":          "https://www.engadget.com/rss.xml",
    "Wired":             "https://www.wired.com/feed/rss",
    "MIT Tech Review":   "https://www.technologyreview.com/feed/",
    "BBC Technology":    "https://feeds.bbci.co.uk/news/technology/rss.xml",
    # --- Қизиқ илм-фан / технология ---
    "ScienceDaily Tech": "https://www.sciencedaily.com/rss/top/technology.xml",
    "New Scientist":     "https://www.newscientist.com/feed/home/",
    # --- Дунё янгиликлари ---
    "BBC World":         "https://feeds.bbci.co.uk/news/world/rss.xml",
    "Al Jazeera":        "https://www.aljazeera.com/xml/rss/all.xml",
}

# Сиз берган муҳаррирлик қоидалари — Claude'нинг system промпти
EDITOR_SYSTEM_PROMPT = """Сен профессионал журналист ва оммабоп технологик Telegram канал муҳарририсан.
Канал мавзуси: IT, AI, қизиқарли технологиялар ва муҳим дунё янгиликлари.

Вазифанг: берилган янгиликни таҳлил қилиб, ўзбек тилида (кирилл) ўқувчини
жалб қиладиган, тайёр Telegram пост ёзиш.

Қоидалар:
1. Янгиликни оддий таржима қилма — жонли, қизиқарли тилда қайта ёз.
2. Сарлавҳа диққат тортсин, лекин ёлғон ваъда ёки clickbait бўлмасин (фақат ҳақиқат).
3. Биринчи жумла ўқувчини "ушлаб" қолсин — нега бу муҳим ёки қизиқ эканини дарров кўрсат.
4. Энг муҳим фактларни ажрат, сувли гап бўлмасин.
5. Профессионал, аммо жонли ва содда услуб (мураккаб атамаларни тушунтир).
6. Бутун пост 700 белгидан ошмасин.
7. Манбани АЛБАТТА кўрсат: манба номи ва берилган ҳавола.
8. Камида 3 та мос тег қўш.
9. Ҳеч қачон шахсий фикр билдирма.
10. Агар янгилик муҳим ёки қизиқарли бўлмаса, фақат "SKIP" деб қайтар (бошқа ҳеч нима эмас).

Пост формати (айнан шу шаклда):

📰 САРЛАВҲА

Қизиқарли биринчи жумла + қисқача мазмун (2-4 абзац).

⚡ Асосий фактлар:
• ...
• ...
• ...

🔗 Манба: <манба номи> — <ҳавола>

#теглар

Жавоб ФАҚАТ тайёр пост ёки "SKIP" бўлсин. Ортиқча изоҳ ёзма."""

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("news_bot")

HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; NewsBot/1.0)"}
client = Anthropic(api_key=ANTHROPIC_API_KEY)


# ---------------------------------------------------------------------------
# Ҳолатни (такрорламаслик учун) сақлаш
# ---------------------------------------------------------------------------
def load_state():
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            return set(json.load(f).get("posted", []))
    except Exception:
        return set()


def save_state(posted_links):
    # охирги 600 тасини сақлаб қоламиз
    data = {"posted": list(posted_links)[-600:]}
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)


# ---------------------------------------------------------------------------
# Янгиликларни йиғиш
# ---------------------------------------------------------------------------
def clean_text(raw, limit=600):
    txt = BeautifulSoup(raw or "", "html.parser").get_text(" ", strip=True)
    return html.unescape(txt)[:limit]


def feed_image(entry):
    """RSS ичидан расм топишга уриниш."""
    for key in ("media_content", "media_thumbnail"):
        media = entry.get(key)
        if media and isinstance(media, list) and media[0].get("url"):
            return media[0]["url"]
    for link in entry.get("links", []):
        if link.get("type", "").startswith("image") and link.get("href"):
            return link["href"]
    return None


def fetch_candidates():
    cutoff = datetime.now(timezone.utc) - timedelta(hours=LOOKBACK_HOURS)
    items = []
    for source, url in SOURCES.items():
        try:
            feed = feedparser.parse(url, request_headers=HEADERS)
        except Exception as e:
            log.warning("Манба ўқилмади (%s): %s", source, e)
            continue
        for entry in feed.entries[:15]:
            link = entry.get("link")
            if not link:
                continue
            published = None
            if entry.get("published_parsed"):
                published = datetime(*entry.published_parsed[:6], tzinfo=timezone.utc)
            # вақти номаълум бўлса ҳам қабул қиламиз
            if published and published < cutoff:
                continue
            items.append({
                "source": source,
                "title": clean_text(entry.get("title", ""), 200),
                "link": link,
                "summary": clean_text(entry.get("summary", ""), 600),
                "image": feed_image(entry),
                "published": published or datetime.now(timezone.utc),
            })
    items.sort(key=lambda x: x["published"], reverse=True)
    log.info("Жами %d та номзод йиғилди", len(items))
    return items[:25]   # танлов промптини кичик ушлаб турамиз


def get_og_image(page_url):
    """Мақола саҳифасидан og:image ни олиш."""
    try:
        r = requests.get(page_url, headers=HEADERS, timeout=15)
        soup = BeautifulSoup(r.text, "html.parser")
        for prop in ("og:image", "twitter:image"):
            tag = soup.find("meta", property=prop) or soup.find("meta", attrs={"name": prop})
            if tag and tag.get("content"):
                return tag["content"]
    except Exception as e:
        log.debug("og:image олинмади: %s", e)
    return None


# ---------------------------------------------------------------------------
# Claude билан ишлаш
# ---------------------------------------------------------------------------
def select_top(items, n):
    """Энг муҳим n та янгилик индексларини танлайди."""
    listing = "\n".join(
        f"{i}. [{it['source']}] {it['title']}" for i, it in enumerate(items)
    )
    prompt = (
        f"Қуйида технологик янгиликлар рўйхати. Энг муҳим ва ўқувчиларга қизиқарли "
        f"бўлган {n} тасини танла. Реклама, майда ва аҳамиятсиз хабарларни четла.\n\n"
        f"{listing}\n\n"
        f"Жавоб ФАҚАТ JSON массив бўлсин, масалан: [0, 3, 5]. Бошқа ҳеч нима ёзма."
    )
    try:
        msg = client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=200,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = msg.content[0].text.strip()
        raw = re.sub(r"```(json)?", "", raw).strip()
        idx = json.loads(raw)
        idx = [i for i in idx if isinstance(i, int) and 0 <= i < len(items)]
        return idx[:n]
    except Exception as e:
        log.warning("Танлов хатоси, биринчи %d та олинди: %s", n, e)
        return list(range(min(n, len(items))))


def rewrite(item):
    """Битта янгиликни тайёр Telegram постга айлантиради. SKIP бўлса None."""
    user_content = (
        f"Манба номи: {item['source']}\n"
        f"Ҳавола: {item['link']}\n"
        f"Сарлавҳа: {item['title']}\n"
        f"Мазмун: {item['summary']}"
    )
    try:
        msg = client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=900,
            system=EDITOR_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_content}],
        )
        text = msg.content[0].text.strip()
        if text.upper().startswith("SKIP") or len(text) < 30:
            return None
        return text
    except Exception as e:
        log.warning("Қайта ёзиш хатоси: %s", e)
        return None


# ---------------------------------------------------------------------------
# Telegram'га жойлаш
# ---------------------------------------------------------------------------
def post_to_telegram(text, image_url):
    api = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}"
    if CHANNEL_SIGNATURE:
        text = f"{text}\n\n{CHANNEL_SIGNATURE}"
    try:
        if image_url and len(text) <= 1024:
            r = requests.post(f"{api}/sendPhoto", data={
                "chat_id": TELEGRAM_CHANNEL,
                "photo": image_url,
                "caption": text,
            }, timeout=30)
            if r.json().get("ok"):
                return True
            log.warning("sendPhoto муваффақиятсиз, матн билан юбориляпти: %s",
                        r.json().get("description"))
        r = requests.post(f"{api}/sendMessage", data={
            "chat_id": TELEGRAM_CHANNEL,
            "text": text,
            "disable_web_page_preview": False,
        }, timeout=30)
        return r.json().get("ok", False)
    except Exception as e:
        log.error("Telegram'га юбориш хатоси: %s", e)
        return False


# ---------------------------------------------------------------------------
# Асосий оқим
# ---------------------------------------------------------------------------
def main():
    missing = [k for k, v in {
        "ANTHROPIC_API_KEY": ANTHROPIC_API_KEY,
        "TELEGRAM_BOT_TOKEN": TELEGRAM_BOT_TOKEN,
        "TELEGRAM_CHANNEL": TELEGRAM_CHANNEL,
    }.items() if not v]
    if missing:
        log.error(".env да тўлдирилмаган: %s", ", ".join(missing))
        return

    posted = load_state()
    candidates = [it for it in fetch_candidates() if it["link"] not in posted]
    if not candidates:
        log.info("Янги янгилик йўқ.")
        return

    top_idx = select_top(candidates, POSTS_PER_DAY)
    log.info("Танланди: %d та", len(top_idx))

    published_count = 0
    for i in top_idx:
        item = candidates[i]
        post_text = rewrite(item)
        if not post_text:
            log.info("SKIP: %s", item["title"][:60])
            posted.add(item["link"])      # қайта урунмаслик учун
            continue

        image = item["image"] or get_og_image(item["link"])
        if post_to_telegram(post_text, image):
            published_count += 1
            posted.add(item["link"])
            log.info("✓ Жойланди: %s", item["title"][:60])
            save_state(posted)
            time.sleep(DELAY_BETWEEN_POSTS)
        else:
            log.warning("✗ Жойланмади: %s", item["title"][:60])

    save_state(posted)
    log.info("Тугади. Жами жойланган: %d та", published_count)


if __name__ == "__main__":
    main()
