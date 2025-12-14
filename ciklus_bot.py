import logging
import os
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from datetime import datetime, timedelta, time as dtime
from zoneinfo import ZoneInfo

import requests
import random

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    ConversationHandler,
    PicklePersistence,
    filters,
)

TZ = ZoneInfo("Europe/Belgrade")

logging.basicConfig(
    format="%(asctime)s %(name)s %(levelname)s %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

TOKEN = os.getenv("BOT_TOKEN")
if not TOKEN:
    raise RuntimeError("BOT_TOKEN env variable nije podesena")

PORT = int(os.getenv("PORT", "10000"))

WEATHER_API_KEY = os.getenv("WEATHER_API_KEY")
DEFAULT_CITY = os.getenv("DEFAULT_CITY", "Belgrade,RS")

PERSISTENCE_PATH = os.getenv("PERSISTENCE_PATH", "bot_data.pkl")

HOROSCOPE_SIGNS = [
    "Ovan", "Bik", "Blizanac", "Rak", "Lav", "Devica",
    "Vaga", "Škorpija", "Strelac", "Jarac", "Vodolija", "Ribe"
]

(
    SET_CYCLE_LENGTH,
    SET_PERIOD_LENGTH,
    SET_LAST_START,
    SET_STAR_SIGN,
) = range(4)

class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"OK")

def start_health_server():
    server = HTTPServer(("0.0.0.0", PORT), HealthHandler)
    print(f"[health] Listening on port {PORT}")
    server.serve_forever()

def _job_name(chat_id: int) -> str:
    return f"daily22_{chat_id}"

def get_user(application, chat_id: int) -> dict:
    data = application.chat_data.setdefault(chat_id, {})
    data.setdefault("cycle_length", 28)
    data.setdefault("period_length", 5)
    data.setdefault("last_start", None)      # date
    data.setdefault("star_sign", None)       # str
    data.setdefault("daily22_enabled", False)
    return data

def main_menu_keyboard(user: dict | None = None) -> InlineKeyboardMarkup:
    enabled = bool(user and user.get("daily22_enabled"))
    daily_label = "🔕 Dnevna poruka 22:00, isključi" if enabled else "🔔 Dnevna poruka 22:00, uključi"

    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("📅 Podesi ciklus", callback_data="setup")],
            [InlineKeyboardButton("📊 Moj ciklus", callback_data="status")],
            [InlineKeyboardButton(daily_label, callback_data="toggle_daily22")],
            [InlineKeyboardButton("📍 Trenutni dan", callback_data="today")],
        ]
    )

def mood_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("🌟 Sjajan", callback_data="mood_sjajan"),
                InlineKeyboardButton("😐 Onako", callback_data="mood_onako"),
            ],
            [
                InlineKeyboardButton("😣 Težak", callback_data="mood_tezak"),
                InlineKeyboardButton("🔥 Stresan", callback_data="mood_stresan"),
            ],
        ]
    )

def sign_keyboard() -> InlineKeyboardMarkup:
    rows = []
    row = []
    for i, sign in enumerate(HOROSCOPE_SIGNS, start=1):
        row.append(InlineKeyboardButton(sign, callback_data=f"sign_{sign}"))
        if i % 3 == 0:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    rows.append([InlineKeyboardButton("Preskoči", callback_data="sign_skip")])
    return InlineKeyboardMarkup(rows)

def parse_date(text: str):
    t = text.strip()
    for fmt in ["%d.%m.%Y.", "%d.%m.%Y"]:
        try:
            return datetime.strptime(t, fmt).date()
        except ValueError:
            continue
    return None

def calc_next_dates(user: dict):
    if not user.get("last_start"):
        return None

    last_start = user["last_start"]
    cycle = int(user["cycle_length"])
    period_len = int(user["period_length"])

    next_start = last_start + timedelta(days=cycle)
    fertile_start = last_start + timedelta(days=cycle - 18)
    fertile_end = last_start + timedelta(days=cycle - 12)
    period_end = last_start + timedelta(days=period_len)

    return {
        "next_start": next_start,
        "fertile_start": fertile_start,
        "fertile_end": fertile_end,
        "period_end": period_end,
    }

def get_cycle_state_for_today(user: dict):
    if not user.get("last_start"):
        return None, None

    today = datetime.now(TZ).date()
    delta_days = (today - user["last_start"]).days
    if delta_days < 0:
        return None, None

    day_of_cycle = delta_days + 1
    period_len = int(user.get("period_length", 5))

    if day_of_cycle <= period_len:
        phase = "menstrualna faza"
    elif day_of_cycle <= 13:
        phase = "folikularna faza"
    elif day_of_cycle == 14:
        phase = "ovulacija"
    else:
        phase = "luteinska faza"

    return day_of_cycle, phase

def fetch_weather_category():
    if not WEATHER_API_KEY:
        return None, None

    try:
        url = (
            "https://api.openweathermap.org/data/2.5/weather"
            f"?q={DEFAULT_CITY}&appid={WEATHER_API_KEY}&units=metric&lang=sr"
        )
        resp = requests.get(url, timeout=6)
        data = resp.json()

        if "weather" not in data or not data["weather"]:
            return None, None

        main = data["weather"][0]["main"].lower()
        desc = data["weather"][0].get("description", "")

        if "rain" in main or "drizzle" in main or "thunder" in main or "snow" in main:
            return "kisovito", desc
        if "clear" in main:
            return "suncano", desc
        return "oblacno", desc

    except Exception as e:
        logger.warning(f"Greska pri citanju vremena {e}")
        return None, None

def _weather_part(weather_cat: str | None) -> str:
    if weather_cat == "suncano":
        return (
            "☀️ *Vremenski utisak*\n"
            "Sunce cesto podigne energiju, ali ne znaci da moras da budes na 100 posto.\n\n"
        )
    if weather_cat == "kisovito":
        return (
            "🌧️ *Vremenski utisak*\n"
            "Kisni dan ume da spusti raspolozenje i fokus, normalno je ako si usporenija.\n\n"
        )
    if weather_cat == "oblacno":
        return (
            "☁️ *Vremenski utisak*\n"
            "Oblacno cesto donese taj tihi umor, ne dramatizuj, samo prilagodi tempo.\n\n"
        )
    return ""

def _phase_part(phase: str) -> str:
    if "menstrualna" in phase:
        return (
            "🩸 *Menstrualna faza*\n"
            "Moguci su grcevi, pad energije, veca osetljivost, spusti gas bez krivice.\n\n"
        )
    if "folikularna" in phase:
        return (
            "🌱 *Folikularna faza*\n"
            "Energija cesto raste, lakse se uvodi rutina i pokret.\n\n"
        )
    if "ovulacija" in phase:
        return (
            "💛 *Ovulacija*\n"
            "Cesto peak faza, vise energije i samopouzdanja, dobar dan za akciju.\n\n"
        )
    return (
        "🌙 *Luteinska faza*\n"
        "Cesce su natecenost, promena raspolozenja i veca glad, hormoni rade svoje.\n\n"
    )

def _tip_part(phase: str) -> str:
    if "menstrualna" in phase:
        return "✅ *Savet*\nTopla hrana, voda, lagana setnja, san, i manje pritiska na sebe."
    if "folikularna" in phase:
        return "✅ *Savet*\nUvedi jednu naviku, trening, setnja ili plan obroka, telo sada voli tempo."
    if "ovulacija" in phase:
        return "✅ *Savet*\nJaci trening, bitne odluke, izlazak iz zone komfora, dobra energija."
    return "✅ *Savet*\nProteini i vlakna, redovni obroci, i vise razumevanja prema sebi."

def fetch_daily_horoscope(star_sign: str | None) -> str:
    if not star_sign:
        return "Ako hoces horoskop u poruci, podesi znak kroz Podesi ciklus. 💫"

    messages = [
        f"🔮 *Horoskop*\nZa *{star_sign}*, danas je dan za jednu malu ali jasnu odluku. Ne razvlaci, preseci.",
        f"🔮 *Horoskop*\n*{star_sign}* ima dobru energiju za zatvaranje obaveza. Zavrsis jednu stvar, i mir u glavi skoci.",
        f"🔮 *Horoskop*\nZa *{star_sign}*, bolje malo manje ljudi, malo vise fokusa. Mir ti danas vredi zlata.",
        f"🔮 *Horoskop*\n*{star_sign}*, kreativnost ti je jaca, iskoristi to za nesto konkretno, ne samo za mastanje.",
    ]
    return random.choice(messages)

def build_today_overview(day_of_cycle: int, phase: str, weather_cat: str | None, star_sign: str | None) -> str:
    base = f"📍 *Danas je {day_of_cycle}. dan ciklusa* (_{phase}_)\n\n"
    closing = "\n\n🤍 Kad razumes kontekst, lakse prestanes da se krivis i pocnes da saradjujes sa sobom."
    horoscope = fetch_daily_horoscope(star_sign)
    return base + _weather_part(weather_cat) + _phase_part(phase) + horoscope + "\n\n" + _tip_part(phase) + closing

def build_mood_message(mood: str, day_of_cycle: int, phase: str, weather_cat: str | None) -> str:
    header = f"🧠 *Tvoj dnevni uvid*\nDanas je {day_of_cycle}. dan ciklusa (_{phase}_)\n\n"
    weather = _weather_part(weather_cat)
    phase_part = _phase_part(phase)

    if mood == "sjajan":
        mood_part = "🌟 *Sjajan dan*\nZapamti sta je radilo, san, hrana, ljudi, pokret, i ponovi sutra."
    elif mood == "onako":
        mood_part = "😐 *Onako dan*\nJedna mala korekcija sutra, voda, setnja, obrok, i dan ide u plus."
    elif mood == "tezak":
        mood_part = "😣 *Tezak dan*\nNe znaci da si slaba, znaci da je bilo tesko. Sutra spusti gas i cuvaj energiju."
    else:
        mood_part = "🔥 *Stresan dan*\nStres nije tvoj identitet. Sutra izbaci jednu stvar koja te gazi."

    closing = "\n\n🤍 Hvala ti sto si prijavila dan, to je briga o sebi, ne glupost."
    return header + weather + phase_part + mood_part + "\n\n" + _tip_part(phase) + closing

def remove_job_if_exists(job_name: str, context: ContextTypes.DEFAULT_TYPE) -> bool:
    jq = context.application.job_queue
    if jq is None:
        return False
    jobs = jq.get_jobs_by_name(job_name)
    if not jobs:
        return False
    for j in jobs:
        j.schedule_removal()
    return True

async def daily22_job(context: ContextTypes.DEFAULT_TYPE):
    job = context.job
    chat_id = job.chat_id
    user = get_user(context.application, chat_id)

    day_of_cycle, phase = get_cycle_state_for_today(user)
    if day_of_cycle is None:
        await context.bot.send_message(
            chat_id=chat_id,
            text="⏰ 22:00 poruka\nNemam datum ciklusa, udji na Podesi ciklus i unesi datum.",
            reply_markup=main_menu_keyboard(user),
        )
        return

    weather_cat, _ = fetch_weather_category()
    text = build_today_overview(day_of_cycle, phase, weather_cat, user.get("star_sign"))

    tail = "\n\nAko zelis, prijavi raspolozenje jednim klikom."
    await context.bot.send_message(
        chat_id=chat_id,
        text=text + tail,
        reply_markup=mood_keyboard(),
        parse_mode="Markdown",
    )

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    user = get_user(context.application, chat_id)

    text = (
        "Hej, ja sam bot za ciklus, vreme i mali astro dodatak. 🤖🩸💫\n\n"
        "Ako ukljucis dnevnu poruku u 22:00, saljem automatski uvid, i nudim dugmad za raspolozenje.\n\n"
        "Izaberi opciju."
    )
    await update.message.reply_text(text, reply_markup=main_menu_keyboard(user), parse_mode="Markdown")

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "/start, meni\n/stop, ugasi dnevnu poruku u 22:00",
    )

async def stop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    user = get_user(context.application, chat_id)

    job_name = _job_name(chat_id)
    removed = remove_job_if_exists(job_name, context)

    user["daily22_enabled"] = False
    await update.message.reply_text(
        "Ugaseno, nema vise poruke u 22:00." if removed else "Nije bilo ukljuceno.",
        reply_markup=main_menu_keyboard(user),
    )

async def cb_router(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    chat_id = query.message.chat.id
    user = get_user(context.application, chat_id)
    data = query.data

    if data.startswith("mood_"):
        mood_key = data.split("_", 1)[1]
        day_of_cycle, phase = get_cycle_state_for_today(user)
        if day_of_cycle is None:
            await query.edit_message_text(
                "Nemam datum ciklusa, udji na Podesi ciklus i unesi datum.",
                reply_markup=main_menu_keyboard(user),
            )
            return ConversationHandler.END

        weather_cat, _ = fetch_weather_category()
        text = build_mood_message(mood_key, day_of_cycle, phase, weather_cat)
        await query.edit_message_text(text, reply_markup=main_menu_keyboard(user), parse_mode="Markdown")
        return ConversationHandler.END

    if data == "status":
        info = calc_next_dates(user)
        if not user.get("last_start"):
            text = "Nemam datum poslednje menstruacije, udji na Podesi ciklus i unesi datum."
        else:
            text = (
                f"📊 *Trenutne postavke*\n\n"
                f"• Duzina ciklusa, *{user['cycle_length']}* dana\n"
                f"• Trajanje menstruacije, *{user['period_length']}* dana\n"
                f"• Poslednji pocetak, *{user['last_start'].strftime('%d.%m.%Y.')}*\n"
            )
            if user.get("star_sign"):
                text += f"• Horoskopski znak, *{user['star_sign']}*\n"
            if info:
                text += (
                    "\n📆 *Procene*\n"
                    f"• Sledeca menstruacija oko, *{info['next_start'].strftime('%d.%m.%Y.')}*\n"
                    f"• Plodni dani, *{info['fertile_start'].strftime('%d.%m.%Y.')}* do *{info['fertile_end'].strftime('%d.%m.%Y.')}*\n"
                    f"• Kraj menstruacije, *{info['period_end'].strftime('%d.%m.%Y.')}*\n\n"
                    "_Sve su ovo procene._"
                )
        await query.edit_message_text(text, reply_markup=main_menu_keyboard(user), parse_mode="Markdown")
        return ConversationHandler.END

    if data == "today":
        day_of_cycle, phase = get_cycle_state_for_today(user)
        if day_of_cycle is None:
            text = "Nemam datum ciklusa, udji na Podesi ciklus i unesi datum."
        else:
            weather_cat, _ = fetch_weather_category()
            text = build_today_overview(day_of_cycle, phase, weather_cat, user.get("star_sign"))
        await query.edit_message_text(text, reply_markup=main_menu_keyboard(user), parse_mode="Markdown")
        return ConversationHandler.END

    if data == "toggle_daily22":
        jq = context.application.job_queue
        job_name = _job_name(chat_id)

        if user.get("daily22_enabled"):
            remove_job_if_exists(job_name, context)
            user["daily22_enabled"] = False
            await query.edit_message_text("Dnevna poruka u 22:00 je iskljucena.", reply_markup=main_menu_keyboard(user))
            return ConversationHandler.END

        if jq is not None:
            jq.run_daily(
                daily22_job,
                time=dtime(hour=22, minute=0, tzinfo=TZ),
                name=job_name,
                chat_id=chat_id,
            )
        user["daily22_enabled"] = True
        await query.edit_message_text("Dnevna poruka u 22:00 je ukljucena.", reply_markup=main_menu_keyboard(user))
        return ConversationHandler.END

    return ConversationHandler.END

async def setup_entry(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("Unesi duzinu ciklusa u danima, 20 do 45, na primer 28:")
    return SET_CYCLE_LENGTH

async def set_cycle_length(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    user = get_user(context.application, chat_id)

    try:
        value = int(update.message.text.strip())
        if value < 20 or value > 45:
            raise ValueError
    except ValueError:
        await update.message.reply_text("Upisi broj dana izmedju 20 i 45, na primer 28:")
        return SET_CYCLE_LENGTH

    user["cycle_length"] = value
    await update.message.reply_text("Ok, sada upisi koliko dana traje menstruacija, 2 do 10, na primer 5:")
    return SET_PERIOD_LENGTH

async def set_period_length(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    user = get_user(context.application, chat_id)

    try:
        value = int(update.message.text.strip())
        if value < 2 or value > 10:
            raise ValueError
    except ValueError:
        await update.message.reply_text("Upisi broj dana izmedju 2 i 10, na primer 5:")
        return SET_PERIOD_LENGTH

    user["period_length"] = value
    await update.message.reply_text("Super, posalji datum poslednje menstruacije, format dd.mm.gggg. na primer 21.11.2025.")
    return SET_LAST_START

async def set_last_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    user = get_user(context.application, chat_id)

    date_obj = parse_date(update.message.text)
    if not date_obj:
        await update.message.reply_text("Ne mogu da procitam datum, posalji dd.mm.gggg. na primer 21.11.2025.")
        return SET_LAST_START

    user["last_start"] = date_obj

    await update.message.reply_text(
        "Zabelezio sam datum. Sada izaberi horoskopski znak, ili preskoci.",
        reply_markup=sign_keyboard(),
    )
    return SET_STAR_SIGN

async def set_star_sign(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    chat_id = query.message.chat.id
    user = get_user(context.application, chat_id)

    if query.data == "sign_skip":
        user["star_sign"] = None
    else:
        user["star_sign"] = query.data.split("_", 1)[1]

    info = calc_next_dates(user)
    sign_txt = user["star_sign"] if user["star_sign"] else "nije podeseno"

    text = "✅ *Podesavanje zavrseno*\n\n"
    if info:
        text += (
            f"• Znak, *{sign_txt}*\n"
            f"• Sledeca menstruacija oko, *{info['next_start'].strftime('%d.%m.%Y.')}*\n"
            f"• Plodni dani, *{info['fertile_start'].strftime('%d.%m.%Y.')}* do *{info['fertile_end'].strftime('%d.%m.%Y.')}*\n"
        )
    text += "\nAko zelis automatsku poruku u 22:00, ukljuci je iz menija."
    await query.edit_message_text(text, reply_markup=main_menu_keyboard(user), parse_mode="Markdown")
    return ConversationHandler.END

async def post_init(application):
    jq = application.job_queue
    if jq is None:
        return

    for chat_id, data in application.chat_data.items():
        try:
            if not data.get("daily22_enabled"):
                continue

            cid = int(chat_id)
            job_name = _job_name(cid)

            for j in jq.get_jobs_by_name(job_name):
                j.schedule_removal()

            jq.run_daily(
                daily22_job,
                time=dtime(hour=22, minute=0, tzinfo=TZ),
                name=job_name,
                chat_id=cid,
            )
        except Exception as e:
            logger.exception(f"post_init reschedule greska {e}")

def main():
    threading.Thread(target=start_health_server, daemon=True).start()

    persistence = PicklePersistence(filepath=PERSISTENCE_PATH)

    app = (
        ApplicationBuilder()
        .token(TOKEN)
        .persistence(persistence)
        .post_init(post_init)
        .build()
    )

    conv_handler = ConversationHandler(
        entry_points=[CallbackQueryHandler(setup_entry, pattern="^setup$")],
        states={
            SET_CYCLE_LENGTH: [MessageHandler(filters.TEXT & ~filters.COMMAND, set_cycle_length)],
            SET_PERIOD_LENGTH: [MessageHandler(filters.TEXT & ~filters.COMMAND, set_period_length)],
            SET_LAST_START: [MessageHandler(filters.TEXT & ~filters.COMMAND, set_last_start)],
            SET_STAR_SIGN: [CallbackQueryHandler(set_star_sign, pattern="^(sign_.*|sign_skip)$")],
        },
        fallbacks=[CommandHandler("start", start)],
        allow_reentry=True,
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("stop", stop))

    app.add_handler(conv_handler)
    app.add_handler(CallbackQueryHandler(cb_router))

    app.run_polling()

if __name__ == "__main__":
    main()
