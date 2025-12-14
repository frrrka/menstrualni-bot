import logging
import os
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from datetime import datetime, timedelta, time as dtime
from zoneinfo import ZoneInfo
import random
import requests

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    ConversationHandler,
    ContextTypes,
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

SET_CYCLE_LENGTH, SET_PERIOD_LENGTH, SET_LAST_START, SET_STAR_SIGN = range(4)


class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"OK")

    def do_HEAD(self):
        self.send_response(200)
        self.end_headers()


def start_health_server():
    server = HTTPServer(("0.0.0.0", PORT), HealthHandler)
    print(f"[health] Listening on port {PORT}")
    server.serve_forever()


def job_name_daily(chat_id: int) -> str:
    return f"daily22_{chat_id}"


def ensure_user_defaults(context: ContextTypes.DEFAULT_TYPE) -> dict:
    data = context.chat_data
    data.setdefault("cycle_length", 28)
    data.setdefault("period_length", 5)
    data.setdefault("last_start", None)        # date
    data.setdefault("star_sign", None)         # str
    data.setdefault("daily22_enabled", False)  # bool
    return data


def main_menu_keyboard(daily_enabled: bool) -> InlineKeyboardMarkup:
    daily_label = "🔕 Dnevna poruka 22:00, isključi" if daily_enabled else "🔔 Dnevna poruka 22:00, uključi"
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
    cycle = int(user.get("cycle_length", 28))
    period_len = int(user.get("period_length", 5))

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


def weather_part(weather_cat: str | None) -> str:
    if weather_cat == "suncano":
        return (
            "☀️ Vremenski utisak\n"
            "Sunce cesto podigne energiju, ali ne znaci da moras da guras na maksimum.\n\n"
        )
    if weather_cat == "kisovito":
        return (
            "🌧️ Vremenski utisak\n"
            "Kisni dan ume da spusti raspolozenje i fokus, normalno je ako si usporenija.\n\n"
        )
    if weather_cat == "oblacno":
        return (
            "☁️ Vremenski utisak\n"
            "Oblacno cesto donese tihi umor, prilagodi tempo, bez drame.\n\n"
        )
    return ""


def phase_part(phase: str) -> str:
    if "menstrualna" in phase:
        return (
            "🩸 Menstrualna faza\n"
            "Moguci su grcevi, pad energije, veca osetljivost, spusti gas bez krivice.\n\n"
        )
    if "folikularna" in phase:
        return (
            "🌱 Folikularna faza\n"
            "Energija cesto raste, lakse se uvodi rutina i pokret.\n\n"
        )
    if "ovulacija" in phase:
        return (
            "💛 Ovulacija\n"
            "Cesto peak faza, vise energije i samopouzdanja, dobar dan za akciju.\n\n"
        )
    return (
        "🌙 Luteinska faza\n"
        "Cesce su natecenost, promena raspolozenja i veca glad, hormoni rade svoje.\n\n"
    )


def tip_part(phase: str) -> str:
    if "menstrualna" in phase:
        return "✅ Savet\nTopla hrana, voda, lagana setnja, san, i manje pritiska na sebe."
    if "folikularna" in phase:
        return "✅ Savet\nUvedi jednu naviku, trening, setnja ili plan obroka, telo sada voli tempo."
    if "ovulacija" in phase:
        return "✅ Savet\nJaci trening, bitne odluke, i sve sto trazis hrabrost."
    return "✅ Savet\nProteini i vlakna, redovni obroci, i vise razumevanja prema sebi."


def daily_horoscope(star_sign: str | None) -> str:
    if not star_sign:
        return "🔮 Horoskop\nAko hoces horoskop u poruci, podesi znak u Podesi ciklus."

    messages = [
        f"🔮 Horoskop\nZa {star_sign}, danas jedna mala odluka pravi razliku, preseci i zavrsi.",
        f"🔮 Horoskop\nZa {star_sign}, fokus na zavrsavanje obaveza, jedna stvar manje u glavi.",
        f"🔮 Horoskop\nZa {star_sign}, manje buke, vise mira, danas ti mir vredi najvise.",
        f"🔮 Horoskop\nZa {star_sign}, kreativnost ti radi, pretvori to u konkretnu akciju.",
    ]
    return random.choice(messages)


def build_today_overview(user: dict) -> str:
    day_of_cycle, phase = get_cycle_state_for_today(user)
    if day_of_cycle is None:
        return (
            "Nemam datum poslednje menstruacije.\n"
            "Udji na Podesi ciklus i unesi datum."
        )

    weather_cat, _ = fetch_weather_category()
    star_sign = user.get("star_sign")

    text = (
        f"📍 Danas je {day_of_cycle}. dan ciklusa, faza je {phase}\n\n"
        f"{weather_part(weather_cat)}"
        f"{phase_part(phase)}"
        f"{daily_horoscope(star_sign)}\n\n"
        f"{tip_part(phase)}\n\n"
        "🤍 Kad razumes kontekst, lakse prestanes da se krivis i pocnes da saradjujes sa sobom."
    )
    return text


def build_mood_message(user: dict, mood_key: str) -> str:
    day_of_cycle, phase = get_cycle_state_for_today(user)
    weather_cat, _ = fetch_weather_category()

    header = f"🧠 Tvoj dnevni uvid\nDanas je {day_of_cycle}. dan ciklusa, faza je {phase}\n\n"
    base = weather_part(weather_cat) + phase_part(phase)

    if mood_key == "sjajan":
        mood = "🌟 Sjajan dan\nZapamti sta je radilo, san, hrana, ljudi, pokret, i ponovi sutra."
    elif mood_key == "onako":
        mood = "😐 Onako dan\nSutra jedna mala korekcija, voda, setnja ili bolji obrok, i dan ide u plus."
    elif mood_key == "tezak":
        mood = "😣 Tezak dan\nNe znaci da si slaba, znaci da je bilo tesko, sutra spusti gas i cuvaj energiju."
    else:
        mood = "🔥 Stresan dan\nStres nije tvoj identitet, sutra izbaci jednu stvar koja te gazi."

    return header + base + mood + "\n\n" + tip_part(phase) + "\n\n🤍 Hvala ti sto si prijavila dan."


def remove_job_if_exists(name: str, context: ContextTypes.DEFAULT_TYPE) -> bool:
    jq = context.application.job_queue
    if jq is None:
        return False
    jobs = jq.get_jobs_by_name(name)
    if not jobs:
        return False
    for j in jobs:
        j.schedule_removal()
    return True


async def daily22_job(context: ContextTypes.DEFAULT_TYPE):
    job = context.job
    chat_id = job.chat_id

    stored = context.application.chat_data.get(chat_id)
    if not stored:
        await context.bot.send_message(
            chat_id=chat_id,
            text="⏰ 22:00 poruka\nNemam tvoje podatke, udji na start i podesi ciklus.",
        )
        return

    overview = build_today_overview(stored)
    tail = "\n\nAko zelis, prijavi raspolozenje jednim klikom."
    await context.bot.send_message(
        chat_id=chat_id,
        text="⏰ Dnevna poruka 22:00\n\n" + overview + tail,
        reply_markup=mood_keyboard(),
    )


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = ensure_user_defaults(context)
    await update.message.reply_text(
        "Hej, ja sam bot za ciklus, vreme i mali astro dodatak. 🤖🩸💫\n\nIzaberi opciju.",
        reply_markup=main_menu_keyboard(bool(user.get("daily22_enabled"))),
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Komande\n/start meni\n/stop gasi dnevnu poruku u 22:00",
    )


async def stop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = ensure_user_defaults(context)
    chat_id = update.effective_chat.id

    removed = remove_job_if_exists(job_name_daily(chat_id), context)
    user["daily22_enabled"] = False

    await update.message.reply_text(
        "Ugaseno, nema vise poruke u 22:00." if removed else "Nije bilo ukljuceno.",
        reply_markup=main_menu_keyboard(False),
    )


async def setup_entry(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    ensure_user_defaults(context)
    await query.edit_message_text("Unesi duzinu ciklusa u danima, 20 do 45, na primer 28:")
    return SET_CYCLE_LENGTH


async def set_cycle_length(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = ensure_user_defaults(context)
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
    user = ensure_user_defaults(context)
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
    user = ensure_user_defaults(context)

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
    user = ensure_user_defaults(context)

    if query.data == "sign_skip":
        user["star_sign"] = None
    else:
        user["star_sign"] = query.data.split("_", 1)[1]

    info = calc_next_dates(user)
    sign_txt = user["star_sign"] if user["star_sign"] else "nije podeseno"

    text = "✅ Podesavanje zavrseno\n\n"
    if info:
        text += (
            f"Znak, {sign_txt}\n"
            f"Sledeca menstruacija oko, {info['next_start'].strftime('%d.%m.%Y.')}\n"
            f"Plodni dani, {info['fertile_start'].strftime('%d.%m.%Y.')} do {info['fertile_end'].strftime('%d.%m.%Y.')}\n\n"
        )
    text += "Ako zelis automatsku poruku u 22:00, ukljuci je iz menija."

    await query.edit_message_text(
        text,
        reply_markup=main_menu_keyboard(bool(user.get("daily22_enabled"))),
    )
    return ConversationHandler.END


async def cb_router(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user = ensure_user_defaults(context)
    chat_id = query.message.chat.id
    data = query.data

    if data.startswith("mood_"):
        mood_key = data.split("_", 1)[1]
        if not user.get("last_start"):
            await query.edit_message_text(
                "Nemam datum poslednje menstruacije. Udji na Podesi ciklus i unesi datum.",
                reply_markup=main_menu_keyboard(bool(user.get("daily22_enabled"))),
            )
            return

        text = build_mood_message(user, mood_key)
        await query.edit_message_text(
            text,
            reply_markup=main_menu_keyboard(bool(user.get("daily22_enabled"))),
        )
        return

    if data == "status":
        info = calc_next_dates(user)
        if not user.get("last_start"):
            text = "Nemam datum poslednje menstruacije. Udji na Podesi ciklus i unesi datum."
        else:
            text = (
                "📊 Trenutne postavke\n\n"
                f"Duzina ciklusa, {user['cycle_length']} dana\n"
                f"Trajanje menstruacije, {user['period_length']} dana\n"
                f"Poslednji pocetak, {user['last_start'].strftime('%d.%m.%Y.')}\n"
                f"Znak, {user['star_sign'] if user.get('star_sign') else 'nije podeseno'}\n"
            )
            if info:
                text += (
                    "\n📆 Procene\n"
                    f"Sledeca menstruacija oko, {info['next_start'].strftime('%d.%m.%Y.')}\n"
                    f"Plodni dani, {info['fertile_start'].strftime('%d.%m.%Y.')} do {info['fertile_end'].strftime('%d.%m.%Y.')}\n"
                    f"Kraj menstruacije, {info['period_end'].strftime('%d.%m.%Y.')}\n"
                )
        await query.edit_message_text(
            text,
            reply_markup=main_menu_keyboard(bool(user.get("daily22_enabled"))),
        )
        return

    if data == "today":
        text = build_today_overview(user)
        await query.edit_message_text(
            text,
            reply_markup=main_menu_keyboard(bool(user.get("daily22_enabled"))),
        )
    
        await query.message.reply_text(
            "Kako ti je prosao dan, izaberi najblizu opciju",
            reply_markup=mood_keyboard(),
        )
        return


    if data == "toggle_daily22":
        jq = context.application.job_queue
        name = job_name_daily(chat_id)

        if user.get("daily22_enabled"):
            remove_job_if_exists(name, context)
            user["daily22_enabled"] = False
            await query.edit_message_text(
                "Iskljucila si dnevnu poruku u 22:00.",
                reply_markup=main_menu_keyboard(False),
            )
            return

        if jq is not None:
            jq.run_daily(
                daily22_job,
                time=dtime(hour=22, minute=0, tzinfo=TZ),
                name=name,
                chat_id=chat_id,
            )
        user["daily22_enabled"] = True
        await query.edit_message_text(
            "Ukljucila si dnevnu poruku u 22:00.",
            reply_markup=main_menu_keyboard(True),
        )
        return


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    logger.exception("Unhandled error", exc_info=context.error)


async def post_init(application):
    jq = application.job_queue
    if jq is None:
        return

    for chat_id, data in application.chat_data.items():
        try:
            if not isinstance(chat_id, int):
                continue
            if not data or not data.get("daily22_enabled"):
                continue

            name = job_name_daily(chat_id)
            for j in jq.get_jobs_by_name(name):
                j.schedule_removal()

            jq.run_daily(
                daily22_job,
                time=dtime(hour=22, minute=0, tzinfo=TZ),
                name=name,
                chat_id=chat_id,
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

    app.add_error_handler(error_handler)

    print("[bot] Starting Telegram bot...")
    app.run_polling()


if __name__ == "__main__":
    main()
    
