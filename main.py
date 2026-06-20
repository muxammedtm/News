#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Telegram автоматик технологик янгиликлар боти — Admin панел билан.

Имкониятлар:
  • Ботнинг ўзида тугмали ADMIN ПАНЕЛ (/start ёки /admin)
  • 📤 Тест: ҳозир дарров 1 та пост чиқариш
  • ⏰ Кунига пост вақтларини созлаш
  • 🔢 Кунига нечта пост чиқишини созлаш
  • 📂 Йўналишларни (IT, Телефон, Илм-фан, Дунё, Бизнес) ёқиш/ўчириш
  • ▶️ Авто-постни ёқиш/ўчириш
  • Созламалар файлда сақланади (қайта ишга тушса йўқолмайди)

Махфий калитлар (env орқали): ANTHROPIC_API_KEY, TELEGRAM_BOT_TOKEN, TELEGRAM_CHANNEL
"""

import os
import re
import json
import time
import html
import logging
import threading
from datetime import datetime, timezone, timedelta
try:
    from zoneinfo import ZoneInfo
except ImportError:
    ZoneInfo = None

import requests
import feedparser
from bs4 import BeautifulSoup
from dotenv import load_dotenv
from anthropic import Anthropic

# ---------------------------------------------------------------------------
# МАХФИЙ КАЛИТЛАР (env)
# ---------------------------------------------------------------------------
load_dotenv()

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "").strip().strip('"').strip("'").strip()
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_CHANNEL = os.getenv("TELEGRAM_CHANNEL", "").strip()
CLAUDE_MODEL = os.getenv("CLAUDE_MODEL", "claude-haiku-4-5-20251001").strip()
TIMEZONE = os.getenv("TIMEZONE", "Asia/Tashkent").strip()
ADMIN_IDS = [int(x) for x in os.getenv("ADMIN_IDS", "610489050").split(",") if x.strip().isdigit()]
DELAY_BETWEEN_POSTS = int(os.getenv("DELAY_BETWEEN_POSTS", "60"))
LOOKBACK_HOURS = int(os.getenv("LOOKBACK_HOURS", "24"))
CHANNEL_SIGNATURE = os.getenv("CHANNEL_SIGNATURE", "").strip()

DATA_DIR = os.getenv("DATA_DIR", os.path.dirname(os.path.abspath(__file__)))
STATE_FILE = os.path.join(DATA_DIR, "state.json")
SETTINGS_FILE = os.path.join(DATA_DIR, "settings.json")

API_ERROR = object()

# ---------------------------------------------------------------------------
# ЙЎНАЛИШЛАР (категориялар) ва уларнинг RSS манбалари
# ---------------------------------------------------------------------------
CATEGORIES = {
    "it": {
        "name": "💻 IT / AI / Технология",
        "sources": {
            "TechCrunch":      "https://techcrunch.com/feed/",
            "The Verge":       "https://www.theverge.com/rss/index.xml",
            "Ars Technica":    "https://feeds.arstechnica.com/arstechnica/index",
            "VentureBeat AI":  "https://venturebeat.com/category/ai/feed/",
            "MIT Tech Review": "https://www.technologyreview.com/feed/",
            "Wired":           "https://www.wired.com/feed/rss",
        },
    },
    "phones": {
        "name": "📱 Телефонлар / Гаджетлар",
        "sources": {
            "GSMArena":         "https://www.gsmarena.com/rss-news-reviews.php3",
            "Engadget":         "https://www.engadget.com/rss.xml",
            "Android Authority":"https://www.androidauthority.com/feed/",
            "9to5Mac":          "https://9to5mac.com/feed/",
        },
    },
    "science": {
        "name": "🔬 Илм-фан",
        "sources": {
            "ScienceDaily":  "https://www.sciencedaily.com/rss/top/technology.xml",
            "New Scientist": "https://www.newscientist.com/feed/home/",
            "Phys.org":      "https://phys.org/rss-feed/",
        },
    },
    "world": {
        "name": "🌍 Дунё янгиликлари",
        "sources": {
            "BBC World":   "https://feeds.bbci.co.uk/news/world/rss.xml",
            "Al Jazeera":  "https://www.aljazeera.com/xml/rss/all.xml",
        },
    },
    "business": {
        "name": "💼 Бизнес / Стартап",
        "sources": {
            "TechCrunch Startups": "https://techcrunch.com/category/startups/feed/",
            "CNBC Tech":           "https://www.cnbc.com/id/19854910/device/rss/rss.html",
        },
    },
}

# ---------------------------------------------------------------------------
# СОЗЛАМАЛАР (файлда сақланади, панелдан ўзгартирилади)
# ---------------------------------------------------------------------------
DEFAULT_SETTINGS = {
    "post_hours": [9, 15, 20],
    "posts_per_day": 8,
    "enabled_categories": ["it", "phones", "science", "world"],
    "auto_enabled": True,
}


def load_settings():
    s = dict(DEFAULT_SETTINGS)
    try:
        with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
            s.update(json.load(f))
    except Exception:
        pass
    # категориялар ҳақиқатан мавжудлигини текшириш
    s["enabled_categories"] = [c for c in s.get("enabled_categories", []) if c in CATEGORIES]
    if not s["enabled_categories"]:
        s["enabled_categories"] = list(CATEGORIES.keys())
    return s


def save_settings(s):
    try:
        os.makedirs(DATA_DIR, exist_ok=True)
        with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
            json.dump(s, f, ensure_ascii=False)
    except Exception as e:
        log.warning("Созламаларни сақлаб бўлмади: %s", e)


# ---------------------------------------------------------------------------
# ЛОГ
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("newsbot")

HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; NewsBot/2.0)"}
client = Anthropic(api_key=ANTHROPIC_API_KEY)
TG_API = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}"

EDITOR_SYSTEM_PROMPT = """Сен профессионал журналист ва оммабоп технологик Telegram канал муҳарририсан.
Канал мавзуси: IT, AI, технология, телефонлар, илм-фан ва муҳим дунё янгиликлари.

Вазифанг: берилган янгиликни таҳлил қилиб, ўзбек тилида (кирилл) ўқувчини жалб қиладиган тайёр Telegram пост ёзиш.

Қоидалар:
1. Оддий таржима эмас — жонли, қизиқарли тилда қайта ёз.
2. Сарлавҳа диққат тортсин, лекин ёлғон ваъда/clickbait бўлмасин.
3. Биринчи жумла ўқувчини "ушлаб" қолсин.
4. Энг муҳим фактларни ажрат, сувли гап бўлмасин.
5. Профессионал, аммо содда услуб; мураккаб атамаларни тушунтир.
6. Бутун пост 700 белгидан ошмасин.
7. Манбани АЛБАТТА кўрсат (манба номи + ҳавола).
8. Камида 3 та мос тег қўш.
9. Ҳеч қачон шахсий фикр билдирма.
10. Янгилик муҳим/қизиқарли бўлмаса, фақат "SKIP" деб қайтар.

Формат:

📰 САРЛАВҲА

Қизиқарли мазмун (2-4 абзац).

⚡ Асосий фактлар:
• ...
• ...
• ...

🔗 Манба: <манба номи> — <ҳавола>

#теглар

Жавоб ФАҚАТ тайёр пост ёки "SKIP" бўлсин."""


# ---------------------------------------------------------------------------
# ҲОЛАТ (такрорламаслик)
# ---------------------------------------------------------------------------
def load_state():
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            return set(json.load(f).get("posted", []))
    except Exception:
        return set()


def save_state(posted):
    try:
        os.makedirs(DATA_DIR, exist_ok=True)
        with open(STATE_FILE, "w", encoding="utf-8") as f:
            json.dump({"posted": list(posted)[-800:]}, f, ensure_ascii=False)
    except Exception as e:
        log.warning("Ҳолатни сақлаб бўлмади: %s", e)


# ---------------------------------------------------------------------------
# ЯНГИЛИК ЙИҒИШ
# ---------------------------------------------------------------------------
def clean_text(raw, limit=600):
    txt = BeautifulSoup(raw or "", "html.parser").get_text(" ", strip=True)
    return html.unescape(txt)[:limit]


def feed_image(entry):
    for key in ("media_content", "media_thumbnail"):
        media = entry.get(key)
        if media and isinstance(media, list) and media[0].get("url"):
            return media[0]["url"]
    for link in entry.get("links", []):
        if link.get("type", "").startswith("image") and link.get("href"):
            return link["href"]
    return None


def active_sources(settings):
    src = {}
    for cat in settings["enabled_categories"]:
        src.update(CATEGORIES[cat]["sources"])
    return src


def fetch_candidates(settings):
    cutoff = datetime.now(timezone.utc) - timedelta(hours=LOOKBACK_HOURS)
    items = []
    for source, url in active_sources(settings).items():
        try:
            feed = feedparser.parse(url, request_headers=HEADERS)
        except Exception as e:
            log.warning("Манба ўқилмади (%s): %s", source, e)
            continue
        for entry in feed.entries[:12]:
            link = entry.get("link")
            if not link:
                continue
            published = None
            if entry.get("published_parsed"):
                published = datetime(*entry.published_parsed[:6], tzinfo=timezone.utc)
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
    return items[:30]


def get_og_image(url):
    try:
        r = requests.get(url, headers=HEADERS, timeout=15)
        soup = BeautifulSoup(r.text, "html.parser")
        for prop in ("og:image", "twitter:image"):
            tag = soup.find("meta", property=prop) or soup.find("meta", attrs={"name": prop})
            if tag and tag.get("content"):
                return tag["content"]
    except Exception:
        pass
    return None


# ---------------------------------------------------------------------------
# CLAUDE
# ---------------------------------------------------------------------------
def select_top(items, n):
    listing = "\n".join(f"{i}. [{it['source']}] {it['title']}" for i, it in enumerate(items))
    prompt = (
        f"Қуйида янгиликлар рўйхати. Энг муҳим ва ўқувчиларга қизиқарли {n} тасини танла. "
        f"Реклама, майда ва аҳамиятсиз хабарларни четла.\n\n{listing}\n\n"
        f"Жавоб ФАҚАТ JSON массив бўлсин, масалан: [0, 3, 5]. Бошқа ҳеч нима ёзма."
    )
    try:
        msg = client.messages.create(
            model=CLAUDE_MODEL, max_tokens=200,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = re.sub(r"```(json)?", "", msg.content[0].text.strip()).strip()
        idx = [i for i in json.loads(raw) if isinstance(i, int) and 0 <= i < len(items)]
        return idx[:n]
    except Exception as e:
        log.warning("Танлов хатоси: %s", e)
        return None


def rewrite(item):
    content = (f"Манба номи: {item['source']}\nҲавола: {item['link']}\n"
               f"Сарлавҳа: {item['title']}\nМазмун: {item['summary']}")
    try:
        msg = client.messages.create(
            model=CLAUDE_MODEL, max_tokens=900,
            system=EDITOR_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": content}],
        )
        text = msg.content[0].text.strip()
        if text.upper().startswith("SKIP") or len(text) < 30:
            return None
        return text
    except Exception as e:
        log.warning("Қайта ёзиш хатоси: %s", e)
        return API_ERROR


# ---------------------------------------------------------------------------
# КАНАЛГА ЖОЙЛАШ
# ---------------------------------------------------------------------------
def post_to_channel(text, image_url):
    if CHANNEL_SIGNATURE:
        text = f"{text}\n\n{CHANNEL_SIGNATURE}"
    try:
        if image_url and len(text) <= 1024:
            r = requests.post(f"{TG_API}/sendPhoto", data={
                "chat_id": TELEGRAM_CHANNEL, "photo": image_url, "caption": text,
            }, timeout=30)
            if r.json().get("ok"):
                return True
        r = requests.post(f"{TG_API}/sendMessage", data={
            "chat_id": TELEGRAM_CHANNEL, "text": text, "disable_web_page_preview": False,
        }, timeout=30)
        return r.json().get("ok", False)
    except Exception as e:
        log.error("Каналга юбориш хатоси: %s", e)
        return False


def publish_batch(n):
    """n та янги пост чиқаради. (статус_матни, нечта_жойланди) қайтаради."""
    settings = load_settings()
    posted = load_state()
    candidates = [it for it in fetch_candidates(settings) if it["link"] not in posted]
    if not candidates:
        return "⚠️ Ҳозирча янги янгилик йўқ.", 0

    top = select_top(candidates, n)
    if top is None:
        return "⛔ Claude API хатоси (калит/баланс?).", 0

    count = 0
    for i in top:
        item = candidates[i]
        text = rewrite(item)
        if text is API_ERROR:
            save_state(posted)
            return f"⛔ Claude API хатоси. {count} та жойланди.", count
        if not text:
            posted.add(item["link"])
            continue
        image = item["image"] or get_og_image(item["link"])
        if post_to_channel(text, image):
            count += 1
            posted.add(item["link"])
            save_state(posted)
            log.info("✓ Жойланди: %s", item["title"][:60])
            if count < len(top):
                time.sleep(DELAY_BETWEEN_POSTS)
    save_state(posted)
    if count == 0:
        return "⚠️ Мос янгилик топилмади (барчаси SKIP).", 0
    return f"✅ {count} та пост каналга жойланди!", count


def publish_one():
    settings = load_settings()
    posted = load_state()
    candidates = [it for it in fetch_candidates(settings) if it["link"] not in posted]
    if not candidates:
        return "⚠️ Ҳозирча янги янгилик йўқ."
    for item in candidates[:6]:
        text = rewrite(item)
        if text is API_ERROR:
            return "⛔ Claude API хатоси. Калит/балансни текширинг."
        if not text:
            posted.add(item["link"])
            continue
        image = item["image"] or get_og_image(item["link"])
        if post_to_channel(text, image):
            posted.add(item["link"])
            save_state(posted)
            log.info("✓ Тест пост жойланди: %s", item["title"][:60])
            return "✅ Пост каналга жойланди!"
        return "⛔ Каналга юбориб бўлмади. Бот канал админими?"
    return "⚠️ Мос янгилик топилмади."


# ---------------------------------------------------------------------------
# TELEGRAM ёрдамчилари
# ---------------------------------------------------------------------------
def tg(method, **params):
    if "reply_markup" in params and isinstance(params["reply_markup"], dict):
        params["reply_markup"] = json.dumps(params["reply_markup"])
    try:
        return requests.post(f"{TG_API}/{method}", data=params, timeout=40).json()
    except Exception as e:
        log.warning("tg %s хатоси: %s", method, e)
        return {}


def kb(rows):
    return {"inline_keyboard": rows}


def btn(text, data):
    return {"text": text, "callback_data": data}


# ---------------------------------------------------------------------------
# ADMIN ПАНЕЛ кўринишлари
# ---------------------------------------------------------------------------
def _local_now():
    if ZoneInfo:
        try:
            return datetime.now(ZoneInfo(TIMEZONE))
        except Exception:
            pass
    return datetime.now()


def panel_main():
    s = load_settings()
    hours = ", ".join(f"{h:02d}:00" for h in s["post_hours"]) or "йўқ"
    cats = ", ".join(CATEGORIES[c]["name"].split(" ", 1)[1] for c in s["enabled_categories"])
    auto = "🟢 ЁҚИЛГАН" if s["auto_enabled"] else "🔴 ЎЧИРИЛГАН"
    text = (
        "🎛 <b>Admin панел</b>\n\n"
        f"⏰ Пост вақтлари: <b>{hours}</b>\n"
        f"🔢 Кунига: <b>{s['posts_per_day']} та</b>\n"
        f"📂 Йўналишлар: {cats}\n"
        f"▶️ Авто-пост: {auto}\n"
        f"🤖 Модел: {CLAUDE_MODEL}\n"
        f"🕐 Ҳозир: {_local_now().strftime('%H:%M')} ({TIMEZONE})"
    )
    rows = [
        [btn("📤 Тест: ҳозир 1 пост", "test_post")],
        [btn("⏰ Вақтлар", "menu_hours"), btn("🔢 Сони", "menu_count")],
        [btn("📂 Йўналишлар", "menu_cats")],
        [btn(("⏸ Авто-постни ўчириш" if s["auto_enabled"] else "▶️ Авто-постни ёқиш"), "toggle_auto")],
        [btn("📊 Ҳолат", "status"), btn("🔄 Янгилаш", "refresh")],
    ]
    return text, kb(rows)


def panel_hours():
    text = "⏰ <b>Кунига пост вақтлари</b>\n\nТайёрларидан танланг ёки қўлда киритинг:"
    rows = [
        [btn("09:00", "seth_9")],
        [btn("09:00, 18:00", "seth_9_18")],
        [btn("09:00, 15:00, 20:00", "seth_9_15_20")],
        [btn("08:00, 12:00, 16:00, 20:00", "seth_8_12_16_20")],
        [btn("✏️ Қўлда киритиш", "seth_custom")],
        [btn("⬅️ Орқага", "refresh")],
    ]
    return text, kb(rows)


def panel_count():
    text = "🔢 <b>Кунига нечта пост?</b>\n\nТанланг:"
    rows = [
        [btn("3", "setc_3"), btn("5", "setc_5"), btn("8", "setc_8")],
        [btn("10", "setc_10"), btn("12", "setc_12"), btn("15", "setc_15")],
        [btn("⬅️ Орқага", "refresh")],
    ]
    return text, kb(rows)


def panel_cats():
    s = load_settings()
    text = "📂 <b>Йўналишлар</b>\n\nҚайси мавзулардан пост чиқсин? (босиб ёқинг/ўчиринг)"
    rows = []
    for key, cat in CATEGORIES.items():
        mark = "✅" if key in s["enabled_categories"] else "⬜️"
        rows.append([btn(f"{mark} {cat['name']}", f"cat_{key}")])
    rows.append([btn("⬅️ Орқага", "refresh")])
    return text, kb(rows)


# ---------------------------------------------------------------------------
# ADMIN POLLING (буйруқ + тугма)
# ---------------------------------------------------------------------------
_busy = threading.Lock()
pending_input = {}   # {admin_id: "hours"}


def is_admin(uid):
    return uid in ADMIN_IDS


def send_panel(chat_id):
    text, markup = panel_main()
    tg("sendMessage", chat_id=chat_id, text=text, parse_mode="HTML", reply_markup=markup)


def handle_message(msg):
    uid = msg.get("from", {}).get("id")
    chat_id = msg.get("chat", {}).get("id")
    text = (msg.get("text") or "").strip()
    if not is_admin(uid):
        return

    # қўлда вақт киритиш кутилаётган бўлса
    if pending_input.get(uid) == "hours":
        pending_input.pop(uid, None)
        hrs = sorted({int(x) for x in re.findall(r"\d{1,2}", text) if 0 <= int(x) <= 23})
        if hrs:
            s = load_settings(); s["post_hours"] = hrs; save_settings(s)
            tg("sendMessage", chat_id=chat_id, text=f"✅ Вақтлар сақланди: " +
               ", ".join(f"{h:02d}:00" for h in hrs))
        else:
            tg("sendMessage", chat_id=chat_id, text="⚠️ Тушунмадим. Масалан: 9 15 20")
        send_panel(chat_id)
        return

    if text in ("/start", "/admin", "/panel", "/menu"):
        send_panel(chat_id)
    elif text == "/post":
        tg("sendMessage", chat_id=chat_id, text="⏳ Янгилик танланмоқда...")
        threading.Thread(target=lambda: tg("sendMessage", chat_id=chat_id, text=publish_one()),
                         daemon=True).start()
    elif text == "/help":
        tg("sendMessage", chat_id=chat_id, text=(
            "📋 Буйруқлар:\n/start — admin панел\n/post — 1 та тест пост\n/status — ҳолат"))


def handle_callback(cb):
    uid = cb.get("from", {}).get("id")
    data = cb.get("data", "")
    msg = cb.get("message", {})
    chat_id = msg.get("chat", {}).get("id")
    mid = msg.get("message_id")
    cb_id = cb.get("id")

    if not is_admin(uid):
        tg("answerCallbackQuery", callback_query_id=cb_id, text="Рухсат йўқ")
        return

    def edit(text, markup):
        tg("editMessageText", chat_id=chat_id, message_id=mid, text=text,
           parse_mode="HTML", reply_markup=markup)

    # --- асосий тугмалар ---
    if data == "refresh":
        t, m = panel_main(); edit(t, m); tg("answerCallbackQuery", callback_query_id=cb_id)

    elif data == "menu_hours":
        t, m = panel_hours(); edit(t, m); tg("answerCallbackQuery", callback_query_id=cb_id)

    elif data == "menu_count":
        t, m = panel_count(); edit(t, m); tg("answerCallbackQuery", callback_query_id=cb_id)

    elif data == "menu_cats":
        t, m = panel_cats(); edit(t, m); tg("answerCallbackQuery", callback_query_id=cb_id)

    elif data == "status":
        s = load_settings()
        k = ANTHROPIC_API_KEY
        keyinfo = f"{k[:14]}...{k[-4:]} ({len(k)})" if k else "ЙЎҚ"
        tg("answerCallbackQuery", callback_query_id=cb_id,
           text=f"Калит: {keyinfo}\nАвто: {'ON' if s['auto_enabled'] else 'OFF'}", show_alert=True)

    elif data == "toggle_auto":
        s = load_settings(); s["auto_enabled"] = not s["auto_enabled"]; save_settings(s)
        t, m = panel_main(); edit(t, m)
        tg("answerCallbackQuery", callback_query_id=cb_id,
           text=("Авто-пост ёқилди" if s["auto_enabled"] else "Авто-пост ўчирилди"))

    # --- тест пост ---
    elif data == "test_post":
        if _busy.locked():
            tg("answerCallbackQuery", callback_query_id=cb_id, text="Жараён ишлаяпти, кутинг", show_alert=True)
            return
        tg("answerCallbackQuery", callback_query_id=cb_id, text="⏳ Бошланди...")
        tg("sendMessage", chat_id=chat_id, text="⏳ Янгилик танланмоқда, кутинг...")

        def _do():
            with _busy:
                res = publish_one()
            tg("sendMessage", chat_id=chat_id, text=res)
        threading.Thread(target=_do, daemon=True).start()

    # --- вақт танлаш ---
    elif data.startswith("seth_"):
        if data == "seth_custom":
            pending_input[uid] = "hours"
            tg("answerCallbackQuery", callback_query_id=cb_id)
            tg("sendMessage", chat_id=chat_id,
               text="✏️ Соатларни ёзинг (масалан: 9 15 20). 0–23 оралиғида.")
        else:
            hrs = [int(x) for x in data[len("seth_"):].split("_")]
            s = load_settings(); s["post_hours"] = sorted(set(hrs)); save_settings(s)
            t, m = panel_main(); edit(t, m)
            tg("answerCallbackQuery", callback_query_id=cb_id, text="Вақтлар сақланди ✅")

    # --- сони танлаш ---
    elif data.startswith("setc_"):
        s = load_settings(); s["posts_per_day"] = int(data[len("setc_"):]); save_settings(s)
        t, m = panel_main(); edit(t, m)
        tg("answerCallbackQuery", callback_query_id=cb_id, text="Сақланди ✅")

    # --- категория ёқиш/ўчириш ---
    elif data.startswith("cat_"):
        key = data[len("cat_"):]
        s = load_settings()
        if key in s["enabled_categories"]:
            if len(s["enabled_categories"]) > 1:
                s["enabled_categories"].remove(key)
        else:
            s["enabled_categories"].append(key)
        save_settings(s)
        t, m = panel_cats(); edit(t, m); tg("answerCallbackQuery", callback_query_id=cb_id)

    else:
        tg("answerCallbackQuery", callback_query_id=cb_id)


def admin_polling():
    log.info("Admin polling ишга тушди (admin: %s)", ADMIN_IDS)
    offset = None
    while True:
        try:
            params = {"timeout": 30, "allowed_updates": json.dumps(["message", "callback_query"])}
            if offset:
                params["offset"] = offset
            r = requests.get(f"{TG_API}/getUpdates", params=params, timeout=40)
            for upd in r.json().get("result", []):
                offset = upd["update_id"] + 1
                if "message" in upd:
                    handle_message(upd["message"])
                elif "callback_query" in upd:
                    handle_callback(upd["callback_query"])
        except Exception as e:
            log.warning("Polling хатоси: %s", e)
            time.sleep(5)


# ---------------------------------------------------------------------------
# АВТО-ПОСТ ЖАДВАЛИ
# ---------------------------------------------------------------------------
def scheduler():
    log.info("Жадвал ишга тушди. Вақт минтақаси: %s", TIMEZONE)
    done = None
    while True:
        try:
            s = load_settings()
            now = _local_now()
            slot = (now.date(), now.hour)
            if s["auto_enabled"] and now.hour in s["post_hours"] and slot != done:
                log.info("⏰ Авто-пост вақти (%02d:00). %d та чиқарилмоқда...",
                         now.hour, s["posts_per_day"])
                with _busy:
                    msg, _ = publish_batch(s["posts_per_day"])
                log.info("Авто-пост: %s", msg)
                done = slot
        except Exception as e:
            log.error("Жадвал хатоси: %s", e)
        time.sleep(60)


# ---------------------------------------------------------------------------
# ИШГА ТУШИРИШ
# ---------------------------------------------------------------------------
def main():
    k = ANTHROPIC_API_KEY
    if k:
        log.info("API калит: %s...%s (узунлиги %d)", k[:14], k[-4:], len(k))
    else:
        log.error("⛔ ANTHROPIC_API_KEY ЙЎҚ!")
    for name, val in (("TELEGRAM_BOT_TOKEN", TELEGRAM_BOT_TOKEN),
                      ("TELEGRAM_CHANNEL", TELEGRAM_CHANNEL)):
        if not val:
            log.error("⛔ %s ЙЎҚ!", name)

    s = load_settings()
    log.info("Созламалар: вақтлар=%s, сони=%d, йўналишлар=%s, авто=%s",
             s["post_hours"], s["posts_per_day"], s["enabled_categories"], s["auto_enabled"])

    threading.Thread(target=admin_polling, daemon=True).start()
    scheduler()   # асосий оқим — ботни тирик ушлаб туради


if __name__ == "__main__":
    main()
