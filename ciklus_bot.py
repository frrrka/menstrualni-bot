import logging
import os
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from datetime import datetime, timedelta, time as dtime
from zoneinfo import ZoneInfo
from typing import Optional
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
    data.setdefault("last_start", None)          # date
    data.setdefault("star_sign", None)           # str
    data.setdefault("low_energy_streak", 0)      # int
    data.setdefault("seen_start", False)         # bool
    return data


def main_menu_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("📅 Podesi ciklus", callback_data="setup")],
            [InlineKeyboardButton("📊 Moj ciklus", callback_data="status")],
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


def weather_part(weather_cat: Optional[str]) -> str:
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


def hormone_hack_block() -> str:
    return (
        "🤬 Nisi bas raspolozena\n\n"
        "📉 Osecas pad energije i motivacije\n\n"
        "Da li znas da mozes da hakujes svoj organizam i podignes raspolozenje na visi nivo na kvalitetan nacin\n\n"
        "Nase telo je neverovatan sistem koji proizvodi pozitivne hormone, prirodne boostere srece, zadovoljstva i uzivanja.\n\n"
        "Evo kako mozes da ih aktiviras i preuzmes kontrolu nad svojim osecanjima\n\n"
        "🔋 DOPAMIN, hormon zadovoljstva, oseti nalet snage kroz\n"
        "Kvalitetan san 😴\n"
        "Omiljenu muziku 🎧\n"
        "Fizicku aktivnost 🏃‍♂️\n\n"
        "😊 SEROTONIN, hormon srece\n"
        "Podigni raspolozenje zahvaljujuci\n"
        "Praktikovanju zahvalnosti 🙏\n"
        "Promeni okruzenja 🌿\n"
        "Ostvarivanju ciljeva 🎯\n\n"
        "💖 OKSITOCIN, hormon blazenstva\n"
        "Stvori osecaj bliskosti kroz\n"
        "Molitvu ili meditaciju 🧘‍♀️\n"
        "Velikodusnost 🎁\n"
        "Grljenje 🤗\n\n"
        "🎉 ENDORFIN, hormon uzivanja\n"
        "Uzivi se u trenutku kroz\n"
        "Smeh 😂\n"
        "Seks ❤️\n"
        "Druzenje i ples 💃🕺\n\n"
        "Nemoj cekati da se osecas bolje, preuzmi stvar u svoje ruke 💥"
    )


def is_low_energy_day(phase: str, weather_cat: Optional[str]) -> bool:
    return ("luteinska" in phase) or ("menstrualna" in phase) or (weather_cat in ["oblacno", "kisovito"])


def low_energy_streak_prefix(user: dict) -> str:
    streak = int(user.get("low_energy_streak", 0))
    if streak >= 3:
        return (
            "🧯 Treci dan zaredom niza energija\n"
            "Ne treba ti dodatni pritisak, treba ti stabilizacija.\n"
            "Cilj danas je minimum koji drzi kontrolu, ne maksimum koji te slomi.\n\n"
        )
    if streak == 2:
        return (
            "⚡ Drugi dan zaredom niza energija\n"
            "Normalno je, danas igramo pametno, ne herojski.\n\n"
        )
    return ""


def tip_part(phase: str, weather_cat: Optional[str]) -> str:
    if is_low_energy_day(phase, weather_cat):
        return (
            "⚡ Energija danas moze biti niza\n"
            "Ovo nije dan za forsiranje.\n\n"
            "✅ Mini reset za energiju\n"
            "Zdrav kofein\n"
            "Dobra muzika koja te dize\n"
            "Kratka setnja ili lagano istezanje\n"
            "Druzenje ili bar kontakt sa ljudima koji ti pune baterije\n\n"
            "Ne moras da pobedis dan, dovoljno je da ga ne izgubis."
        )

    if "folikularna" in phase:
        return (
            "✅ Savet\n"
            "Iskoristi rast energije za akciju, trening, setnja, plan obroka, telo sada lakse podnosi napor."
        )

    if "ovulacija" in phase:
        return (
            "✅ Savet\n"
            "Odlican period za jaci trening, sastanke i odluke, fokus i samopouzdanje su prirodno visi."
        )

    return "✅ Savet\nDanas samo drzi rutinu, bez preterivanja."


def daily_horoscope(star_sign: Optional[str]) -> str:
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
    prefix = low_energy_streak_prefix(user)

    text = (
        f"📍 Danas je {day_of_cycle}. dan ciklusa, faza je {phase}\n\n"
        f"{prefix}"
        f"{weather_part(weather_cat)}"
        f"{phase_part(phase)}"
        f"{daily_horoscope(star_sign)}\n\n"
        f"{tip_part(phase, weather_cat)}"
    )

    if is_low_energy_day(phase, weather_cat):
        text += "\n\n" + hormone_hack_block()

    text += (
        "\n\n🤍 Kad razumes kontekst, lakse prestanes da se krivis i pocnes da saradjujes sa sobom."
    )
    return text


def build_mood_message(user: dict, mood_key: str) -> str:
    day_of_cycle, phase = get_cycle_state_for_today(user)
    weather_cat, _ = fetch_weather_category()

    header = f"🧠 Tvoj dnevni uvid\nDanas je {day_of_cycle}. dan ciklusa, faza je {phase}\n\n"
    base = weather_part(weather_cat) + phase_part(phase)

    if mood_key == "sjajan":
        mood = (
            "🌟 Sjajan dan\n"
            "Bravo. Zapamti sta je radilo, san, hrana, ljudi, pokret, i ponovi sutra."
        )
        extra = ""
    elif mood_key == "onako":
        mood = (
            "😐 Onako dan\n"
            "Sivi danovi su najopasniji jer te uspavaju. Sutra jedna mala korekcija i to je pobeda."
        )
        extra = "\n\n" + hormone_hack_block()
    elif mood_key == "tezak":
        mood = (
            "😣 Tezak dan\n"
            "Tezak dan ne znaci da si slaba. Znaci da je bilo tesko. Sutra spusti gas i cuvaj energiju."
        )
        extra = "\n\n" + hormone_hack_block()
    else:
        mood = (
            "🔥 Stresan dan\n"
            "Stres nije tvoj identitet. Sutra izbaci jednu stvar koja te gazi, jednu jedinu."
        )
        extra = "\n\n" + hormone_hack_block()

    tail = "\n\n" + tip_part(phase, weather_cat) + "\n\n🤍 Hvala ti sto si prijavila dan."
    return header + base + mood + extra + tail


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

    day_of_cycle, phase = get_cycle_state_for_today(stored)
    weather_cat, _ = fetch_weather_category()

    if day_of_cycle is not None and phase is not None:
        if is_low_energy_day(phase, weather_cat):
            stored["low_energy_streak"] = int(stored.get("low_energy_streak", 0)) + 1
        else:
            stored["low_energy_streak"] = 0

    overview = build_today_overview(stored)
    tail = "\n\nAko zelis, prijavi raspolozenje jednim klikom."
    await context.bot.send_message(
        chat_id=chat_id,
        text="⏰ Dnevna poruka 22:00\n\n" + overview + tail,
        reply_markup=mood_keyboard(),
    )


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = ensure_user_defaults(context)
    chat_id = update.effective_chat.id

    user["seen_start"] = True

    jq = context.application.job_queue
    name = job_name_daily(chat_id)

    if jq is not None and not jq.get_jobs_by_name(name):
        jq.run_daily(
            daily22_job,
            time=dtime(hour=22, minute=0, tzinfo=TZ),
            name=name,
            chat_id=chat_id,
        )

    await update.message.reply_text(
        "Hej, ja sam bot za ciklus, vreme i raspolozenje. 🤖🩸\n\n"
        "Svako vece u 22:00 dobijas dnevnu poruku automatski.\n"
        "Ako hoces i horoskop, podesi znak kroz Podesi ciklus.\n\n"
        "Izaberi opciju:",
        reply_markup=main_menu_keyboard(),
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Komande\n"
        "/start meni\n\n"
        "Dnevna poruka u 22:00 je automatska.",
        reply_markup=main_menu_keyboard(),
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
    text += "Svako vece u 22:00 dobijas dnevnu poruku automatski."

    await query.edit_message_text(
        text,
        reply_markup=main_menu_keyboard(),
    )
    return ConversationHandler.END


async def cb_router(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    user = ensure_user_defaults(context)
    data = query.data

    if data.startswith("mood_"):
        mood_key = data.split("_", 1)[1]
        if mood_key == "sjajan":
            user["low_energy_streak"] = 0

        if not user.get("last_start"):
            await query.edit_message_text(
                "Nemam datum poslednje menstruacije. Udji na Podesi ciklus i unesi datum.",
                reply_markup=main_menu_keyboard(),
            )
            return

        text = build_mood_message(user, mood_key)
        await query.edit_message_text(
            text,
            reply_markup=main_menu_keyboard(),
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
            reply_markup=main_menu_keyboard(),
        )
        return

    if data == "today":
        text = build_today_overview(user)
        await query.edit_message_text(
            text,
            reply_markup=main_menu_keyboard(),
        )

        await query.message.reply_text(
            "Kako ti je prosao dan, izaberi najblizu opciju",
            reply_markup=mood_keyboard(),
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
            if not isinstance(data, dict):
                continue
            if not data.get("seen_start"):
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

    app.add_handler(conv_handler)
    app.add_handler(CallbackQueryHandler(cb_router))

    app.add_error_handler(error_handler)

    print("[bot] Starting Telegram bot...")
    app.run_polling()


if __name__ == "__main__":
    main()
