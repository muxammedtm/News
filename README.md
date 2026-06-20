# 🤖 Telegram автоматик технологик янгиликлар боти

RSS манбалардан янгиликларни олиб, Claude орқали ўзбекча (кирилл) қайта ёзади ва
расми билан Telegram каналга автоматик жойлайди. Кунига 7–10 пост.

---

## 1. Нима тайёрлаб қўйиш керак

1. **Telegram бот** — Telegram'да [@BotFather](https://t.me/BotFather) га ёзинг →
   `/newbot` → ном беринг → **токен** оласиз.
2. **Ботни канал админи қилинг** — каналингиз → Administrators → ботни қўшинг
   (постлар юбориш ҳуқуқи билан). Бусиз бот ёза олмайди!
3. **Anthropic API калити** — [console.anthropic.com](https://console.anthropic.com) →
   рўйхатдан ўтинг → Billing'дан $10 кредит тўлдиринг → API Keys → калит яратинг.

---

## 2. VPS'га ўрнатиш (bothost)

VPS'га SSH орқали кирганингиздан кейин:

```bash
# Python ва керакли воситалар
sudo apt update && sudo apt install -y python3 python3-pip python3-venv

# Лойиҳа папкаси
mkdir ~/newsbot && cd ~/newsbot

# (бу 4 та файлни шу папкага ташланг: news_bot.py, requirements.txt, .env.example)

# Виртуал муҳит ва кутубхоналар
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

---

## 3. Созлаш

```bash
cp .env.example .env
nano .env        # калитларни тўлдиринг ва сақланг (Ctrl+O, Enter, Ctrl+X)
```

`.env` ичида: `ANTHROPIC_API_KEY`, `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHANNEL` —
шу учтаси албатта тўлдирилиши керак.

---

## 4. Синаб кўриш

```bash
source venv/bin/activate
python3 news_bot.py
```

Каналингизга постлар туша бошласа — ишлаяпти ✅

---

## 5. Ҳар куни автоматик ишлатиш (cron)

```bash
crontab -e
```

Қуйидаги қаторни қўшинг (ҳар куни эртанги соат 9:00 да ишлайди):

```
0 9 * * * cd /root/newsbot && /root/newsbot/venv/bin/python3 news_bot.py >> bot.log 2>&1
```

> ⏰ Соат сервер вақти бўйича. Текшириш: `date`. Папка йўли ҳар хил бўлса
> (`/root/` ёки `/home/user/`) ўзингизникига мослаб ёзинг.

---

## Тез-тез бериладиган саволлар

**Нархи қанча?** Haiku моделда кунига 8 пост ≈ ойига $1.5–2. Кўпроқ сифат
учун `.env` да `CLAUDE_MODEL=claude-sonnet-4-6` қилинг (ойига ~$4–5).

**Манбаларни ўзгартириш?** `news_bot.py` ичидаги `SOURCES` рўйхатига RSS
ҳаволаларини қўшинг ёки ўчиринг.

**Пост сонини ўзгартириш?** `.env` да `POSTS_PER_DAY` ни ўзгартиринг.

**Бир хил янгилик такрорланмайдими?** Йўқ. `state.json` файлида жойланганлар
сақланади, такрорламайди.

**Расм чиқмаяпти?** Баъзи сайтларда расм бўлмаслиги мумкин — у ҳолда фақат
матн жойланади (бу хато эмас).
