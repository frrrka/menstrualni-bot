import logging
from datetime import datetime, timedelta, time as dtime

import requests
from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    ConversationHandler,
    filters,
)

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# --------- KONFIGURACIJA ---------
TOKEN = "8208168695:AAF28Qwwu0pOAR4hHwzELCUmIirPEZaPdqU"

WEATHER_API_KEY = "42d427d7fbdd6ccdfbaa32673d9528ac"
DEFAULT_CITY = "Belgrade,RS"

# --------- STANJA ZA CONVERSATION ---------
(
    SET_CYCLE_LENGTH,
    SET_PERIOD_LENGTH,
    SET_LAST_START,
) = range(3)

USER_DATA = {}


def get_user(chat_id: int):
    if chat_id not in USER_DATA:
        USER_DATA[chat_id] = {
            "cycle_length": 28,
            "period_length": 5,
            "last_start": None,
        }
    return USER_DATA[chat_id]


def main_menu_keyboard():
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("📅 Podesi ciklus", callback_data="setup")],
            [InlineKeyboardButton("📊 Moj ciklus", callback_data="status")],
            [InlineKeyboardButton("🔔 Podsetnik 22:00", callback_data="reminders")],
            [InlineKeyboardButton("📍 Trenutni dan", callback_data="today")],
        ]
    )


def calc_next_dates(user):
    if not user.get("last_start"):
        return None

    last_start = user["last_start"]
    cycle = user["cycle_length"]
    period_len = user["period_length"]

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


def get_cycle_state_for_today(user):
    if not user.get("last_start"):
        return None, None

    today = datetime.now().date()
    delta_days = (today - user["last_start"]).days
    if delta_days < 0:
        return None, None

    day_of_cycle = delta_days + 1

    if day_of_cycle <= 6:
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
            f"https://api.openweathermap.org/data/2.5/weather?"
            f"q={DEFAULT_CITY}&appid={WEATHER_API_KEY}&units=metric&lang=sr"
        )
        resp = requests.get(url, timeout=5)
        data = resp.json()

        if "weather" not in data or not data["weather"]:
            return None, None

        main = data["weather"][0]["main"].lower()
        desc = data["weather"][0].get("description", "").lower()

        if "rain" in main or "drizzle" in main or "thunder" in main:
            return "kisovito", desc
        if "clear" in main:
            return "suncano", desc
        return "oblacno", desc
    except Exception as e:
        logger.warning(f"Greška pri čitanju vremena: {e}")
        return None, None


# --------- TEKST BLOKOVI (sa emoji i razmacima) ---------


def _weather_part(weather_cat: str) -> str:
    if weather_cat == "suncano":
        return (
            "☀️ *Vremenski utisak*\n"
            "Danas je bilo sunčano – takvi dani često daju malo više energije i lakše raspoloženje, "
            "ali to ne znači da svaki put moraš da budeš „na 100%“. Dozvoljeno je da i sunčan dan bude mirniji.\n\n"
        )
    elif weather_cat == "kisovito":
        return (
            "🌧️ *Vremenski utisak*\n"
            "Kišni dani često povuku raspoloženje nadole, pojačaju umor i želju da se zaviješ u ćebe. "
            "Nije problem u tebi – vreme ume ozbiljno da cimne i telo i glavu.\n\n"
        )
    elif weather_cat == "oblacno":
        return (
            "☁️ *Vremenski utisak*\n"
            "Oblačni dani znaju da spuste fokus i motivaciju, kao da je i mozak malo zamućen. "
            "Sasvim je normalno ako si danas bila „usporenija“.\n\n"
        )
    return ""


def _phase_part(phase: str) -> str:
    if "menstrualna" in phase:
        return (
            "🩸 *Menstrualna faza*\n"
            "Telo intenzivno izbacuje sluznicu materice, mogu se javljati bolovi, grčevi i pad energije. "
            "Normalno je da si sporija, osetljivija i da ti više prijaju mir, toplina i jednostavniji dan.\n\n"
        )
    if "folikularna" in phase:
        return (
            "🌱 *Folikularna faza*\n"
            "Energija i izdržljivost često rastu, telo se podiže posle menstruacije i obnavlja se sluznica materice. "
            "Mnoge žene se u ovoj fazi osećaju lakše u glavi i spremnije za akciju.\n\n"
        )
    if "ovulacija" in phase:
        return (
            "💛 *Ovulacija*\n"
            "Ovo je često „peak“ faza – više snage, više samopouzdanja, više želje da budeš među ljudima i u pokretu. "
            "Telo je u fazi kada je biološki najspremnije i to se često vidi i na energiji.\n\n"
        )
    if "luteinska" in phase:
        return (
            "🌙 *Luteinska faza*\n"
            "Druga polovina ciklusa, gde mnoge žene osećaju veću iscrpljenost, pad motivacije, zadržavanje vode, "
            "natečenost i PMS. Promene raspoloženja i pojačana glad su česte i nisu znak slabosti, već hormonskih promena.\n\n"
        )
    return ""


def _tip_part(phase: str) -> str:
    if "menstrualna" in phase:
        return (
            "✅ *Praktičan savet*\n"
            "Smanji očekivanja od sebe, fokusiraj se na toplu hranu, dovoljno tečnosti, "
            "lagano kretanje (šetnja, istezanje) i kvalitetan san. Ovo je vreme kada je skroz ok da spustiš gas."
        )
    if "folikularna" in phase:
        return (
            "✅ *Praktičan savet*\n"
            "Iskoristi rast energije da uvedeš jednu zdravu naviku – trening, šetnju, bolji plan obroka. "
            "Telo sada voli pokret i lakše podnosi napor."
        )
    if "ovulacija" in phase:
        return (
            "✅ *Praktičan savet*\n"
            "Odličan period za jače treninge, društvene aktivnosti, bitne sastanke i odluke. "
            "Iskoristi viši nivo samopouzdanja za stvari koje traže hrabrost."
        )
    # luteinska
    return (
        "✅ *Praktičan savet*\n"
        "Očekuj uspone i padove. Pomaže da obroci budu bogatiji proteinom i vlaknima, da ne preskačeš obroke "
        "i da sebi daš više razumevanja umesto kritike. PMS je realan faktor, nije izgovor."
    )


def build_today_overview(day_of_cycle: int, phase: str, weather_cat: str) -> str:
    base = (
        f"📍 *Danas je {day_of_cycle}. dan od početka tvog ciklusa* "
        f"(_{phase}_).\n\n"
    )
    weather_part = _weather_part(weather_cat)
    phase_part = _phase_part(phase)
    tip_part = _tip_part(phase)

    closing = (
        "\n\n🤍 Ovo nije „običan“ dan – ima svoj hormonalni kontekst. "
        "Kada razumeš šta telo radi, lakše prestaneš da ga kriviš i počneš da sarađuješ sa njim."
    )

    return base + weather_part + phase_part + tip_part + closing


def build_mood_message(mood: str, day_of_cycle: int, phase: str, weather_cat: str) -> str:
    """Trenutni dan + blok za raspoloženje."""
    header = (
        f"🧠 *Kako ti je prošao dan?* \n"
        f"Danas je {day_of_cycle}. dan od početka tvog ciklusa (_{phase}_).\n\n"
    )
    weather_part = _weather_part(weather_cat)
    phase_part = _phase_part(phase)

    if mood == "sjajan":
        mood_part = (
            "🌟 *Raspoloženje: Sjajan dan*\n"
            "Bravo za tebe. U ovoj fazi ciklusa iskoristila si dan kako treba. "
            "Zapamti šta ti je prijalo – rutina, ljudi, hrana, pokret – to su obrasci koje želiš češće da ponavljaš.\n\n"
            "Nisi imala „savršен“ dan, imala si dobar dan za sebe – i to je ono što gradi stabilnost."
        )
    elif mood == "onako":
        mood_part = (
            "😐 *Raspoloženje: Onako dan*\n"
            "Sivi, „ni tamo ni ovamo“ dani su najopasniji, jer lako skliznu u odustajanje. "
            "Nije bilo katastrofe, ali nije bilo ni pobede. Tu praviš razliku malim potezima.\n\n"
            "Zapitaj se: koja je jedna mala stvar koju sutra možeš uraditi bolje – više vode, malo kretanja, pametniji izbor obroka? "
            "Jedan mali korak je dovoljan da dan ode u plus."
        )
    elif mood == "tezak":
        mood_part = (
            "😣 *Raspoloženje: Težak dan*\n"
            "Težak dan ne znači da si slaba, nego da je teret bio ozbiljan. "
            "Pogotovo u ovoj fazi ciklusa, normalno je da se energija lomi, da emocije idu gore-dole i da ti je glava puna.\n\n"
            "Umesto da gledaš samo šta nije uspelo, primeti šta ipak jeste: možda si ispoštovala obrok, "
            "dovukla se do kraja obaveza, našla trenutak da odmoriš ili rekla „ne“ nečemu što ti ne prija. "
            "To su male pobede na koje imaš pravo da budeš ponosna."
        )
    else:  # stresno
        mood_part = (
            "🔥 *Raspoloženje: Stresan dan*\n"
            "Stresan dan iscedi i telo i mozak. U kombinaciji sa ciklusom, to može da znači još više napetosti, "
            "nervoze i osećaja da ti je svega preko glave.\n\n"
            "Ali zapamti: ti nisi tvoj stres. Ti si osoba koja je sve to izgurala do kraja dana. "
            "Nađi jednu lekciju iz dana i jednu stvar na kojoj možeš da zahvališ sebi. "
            "Sutra ne krećeš od nule – krećeš sa iskustvom više."
        )

    tip_part = _tip_part(phase)

    closing = (
        "\n\n🤍 Hvala ti što si stala i prijavila kako ti je danas. "
        "To je već jedan vid brige o sebi."
    )

    return header + weather_part + phase_part + mood_part + "\n\n" + tip_part + closing


# --------- KOMANDE ---------


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    get_user(chat_id)

    text = (
        "Hej, ja sam tvoj lični bot za menstrualni ciklus. 🤖🩸\n\n"
        "Mogu da ti:\n"
        "• pratim ciklus\n"
        "• približno računam plodne dane\n"
        "• šaljem podsetnik SVAKO VEČE u 22:00 da upišeš kakav ti je bio dan\n"
        "• povežem raspoloženje sa fazom ciklusa i vremenom tog dana\n"
        "• kroz „📍 Trenutni dan“ objasnim šta se otprilike sada dešava u tvom telu\n\n"
        "Napomena: nisam doktor, samo alat za organizaciju. Za zdravstvene nedoumice uvek se obrati ginekologu. ❤️\n\n"
        "Izaberi opciju:"
    )

    await update.message.reply_text(text, reply_markup=main_menu_keyboard(), parse_mode="Markdown")


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "/start – meni\n"
        "/stop – gasi podsetnik u 22:00\n\n"
        "Za promenu podataka idi na /start pa '📅 Podesi ciklus'."
    )
    await update.message.reply_text(text, reply_markup=main_menu_keyboard())


async def stop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    job_removed = remove_job_if_exists(str(chat_id), context)
    if job_removed:
        text = "Isključila si podsetnik u 22:00. 🔕"
    else:
        text = "Nisi imala uključen podsetnik."
    await update.message.reply_text(text, reply_markup=main_menu_keyboard())


# --------- JOB 22:00 ---------


def remove_job_if_exists(name: str, context: ContextTypes.DEFAULT_TYPE):
    job_queue = context.application.job_queue
    if job_queue is None:
        return False
    current_jobs = job_queue.get_jobs_by_name(name)
    if not current_jobs:
        return False
    for job in current_jobs:
        job.schedule_removal()
    return True


async def reminder_job(context: ContextTypes.DEFAULT_TYPE):
    job = context.job
    chat_id = job.chat_id
    user = get_user(chat_id)

    day_of_cycle, phase = get_cycle_state_for_today(user)

    if day_of_cycle is None:
        text = (
            "⏰ Podsetnik 22:00\n\n"
            "Nemam podatak o početku ciklusa.\n"
            "Klikni na /start pa '📅 Podesi ciklus' i unesi datum poslednje menstruacije."
        )
        await context.bot.send_message(chat_id, text=text, reply_markup=main_menu_keyboard())
        return

    text = (
        "⏰ Podsetnik 22:00\n\n"
        f"Danas je {day_of_cycle}. dan od početka tvog ciklusa.\n\n"
        "Kako ti je bio dan? Izaberi najbližu opciju:"
    )

    keyboard = [
        [
            InlineKeyboardButton("🌟 Sjajan", callback_data="mood_sjajan"),
            InlineKeyboardButton("😐 Onako", callback_data="mood_onako"),
        ],
        [
            InlineKeyboardButton("😣 Težak", callback_data="mood_tezak"),
            InlineKeyboardButton("🔥 Stresan", callback_data="mood_stresan"),
        ],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await context.bot.send_message(chat_id, text=text, reply_markup=reply_markup)


# --------- CALLBACK DUGMAD ---------


async def button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    chat_id = query.message.chat_id
    data = query.data

    # izbor raspoloženja
    if data.startswith("mood_"):
        mood_key = data.split("_", 1)[1]  # sjajan, onako, tezak, stresan
        await handle_mood_response(query, context, mood_key)
        return ConversationHandler.END

    if data == "setup":
        await query.edit_message_text(
            "Unesi dužinu ciklusa u danima, na primer 28:", reply_markup=None
        )
        return SET_CYCLE_LENGTH

    if data == "status":
        user = get_user(chat_id)
        info = calc_next_dates(user)

        if not user["last_start"]:
            text = (
                "Još uvek nemam podatak kada je poslednja menstruacija počela.\n"
                "Klikni na '📅 Podesi ciklus' i unesi datum."
            )
        else:
            text = (
                f"📊 *Trenutne postavke*\n\n"
                f"• Dužina ciklusa: *{user['cycle_length']}* dana\n"
                f"• Trajanje menstruacije: *{user['period_length']}* dana\n"
                f"• Poslednji početak: *{user['last_start'].strftime('%d.%m.%Y.')}*\n\n"
            )
            if info:
                text += (
                    "📆 *Procene*\n"
                    f"• Sledeća menstruacija oko: *{info['next_start'].strftime('%d.%m.%Y.')}*\n"
                    f"• Plodni dani: *{info['fertile_start'].strftime('%d.%m.%Y.')}* - *{info['fertile_end'].strftime('%d.%m.%Y.')}*\n"
                    f"• Kraj menstruacije: *{info['period_end'].strftime('%d.%m.%Y.')}*\n\n"
                    "_Sve su ovo procene, telo nije kalendar._ 🙂"
                )
        await query.edit_message_text(text, reply_markup=main_menu_keyboard(), parse_mode="Markdown")
        return ConversationHandler.END

    if data == "reminders":
        job_queue = context.application.job_queue
        job_removed = remove_job_if_exists(str(chat_id), context)
        if job_queue is not None:
            job_queue.run_daily(
                reminder_job,
                time=dtime(hour=22, minute=0),
                name=str(chat_id),
                chat_id=chat_id,
            )
        if job_removed:
            text = "Osvežila si svakodnevni podsetnik u 22:00. 🔔"
        else:
            text = "Uključila si svakodnevni podsetnik u 22:00. 🔔"
        await query.edit_message_text(text, reply_markup=main_menu_keyboard())
        return ConversationHandler.END

    if data == "today":
        user = get_user(chat_id)
        day_of_cycle, phase = get_cycle_state_for_today(user)
        if day_of_cycle is None:
            text = (
                "Nemam podatak o početku ciklusa.\n"
                "Klikni na '📅 Podesi ciklus' i unesi datum poslednje menstruacije."
            )
        else:
            weather_cat, weather_desc = fetch_weather_category()
            text = build_today_overview(day_of_cycle, phase, weather_cat)
        await query.edit_message_text(text, reply_markup=main_menu_keyboard(), parse_mode="Markdown")
        return ConversationHandler.END


async def handle_mood_response(query, context: ContextTypes.DEFAULT_TYPE, mood_key: str):
    chat_id = query.message.chat_id
    user = get_user(chat_id)

    day_of_cycle, phase = get_cycle_state_for_today(user)
    if day_of_cycle is None:
        await query.edit_message_text(
            "Nemam podatke o ciklusu. Idi na /start pa '📅 Podesi ciklus'.",
            reply_markup=main_menu_keyboard(),
        )
        return

    weather_cat, weather_desc = fetch_weather_category()
    text = build_mood_message(mood_key, day_of_cycle, phase, weather_cat)

    await query.edit_message_text(text, reply_markup=main_menu_keyboard(), parse_mode="Markdown")


# --------- UNOS CIKLUSA ---------


async def set_cycle_length(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    user = get_user(chat_id)

    try:
        value = int(update.message.text.strip())
        if value < 20 or value > 45:
            raise ValueError
    except ValueError:
        await update.message.reply_text(
            "Upiši broj dana između 20 i 45, na primer 28:"
        )
        return SET_CYCLE_LENGTH

    user["cycle_length"] = value
    await update.message.reply_text(
        "OK. Sada upiši koliko dana obično traje menstruacija, na primer 5:"
    )
    return SET_PERIOD_LENGTH


async def set_period_length(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    user = get_user(chat_id)

    try:
        value = int(update.message.text.strip())
        if value < 2 or value > 10:
            raise ValueError
    except ValueError:
        await update.message.reply_text(
            "Upiši broj dana između 2 i 10, na primer 5:"
        )
        return SET_PERIOD_LENGTH

    user["period_length"] = value
    await update.message.reply_text(
        "Super. Sada mi pošalji datum kada je poslednja menstruacija počela.\n"
        "Format: dd.mm.gggg. na primer 21.11.2025."
    )
    return SET_LAST_START


def parse_date(text: str):
    text = text.strip()
    for fmt in ["%d.%m.%Y.", "%d.%m.%Y"]:
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


async def set_last_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    user = get_user(chat_id)

    date_obj = parse_date(update.message.text)
    if not date_obj:
        await update.message.reply_text(
            "Ne mogu da pročitam datum. Pošalji ga u formatu dd.mm.gggg. na primer 21.11.2025."
        )
        return SET_LAST_START

    user["last_start"] = date_obj
    info = calc_next_dates(user)
    text = (
        "Zabeležio sam datum. 📌\n\n"
        f"Sledeća menstruacija je okvirno oko: {info['next_start'].strftime('%d.%m.%Y.')}\n"
        f"Plodni dani: {info['fertile_start'].strftime('%d.%m.%Y.')} - {info['fertile_end'].strftime('%d.%m.%Y.')}\n\n"
        "Zapamti, ovo su samo procene. Ako imaš bilo kakvih zdravstvenih nedoumica, javi se svom ginekologu. ❤️"
    )
    await update.message.reply_text(text, reply_markup=main_menu_keyboard())
    return ConversationHandler.END


# --------- MAIN ---------


def main():
    app = ApplicationBuilder().token(TOKEN).build()

    conv_handler = ConversationHandler(
        entry_points=[CallbackQueryHandler(button)],
        states={
            SET_CYCLE_LENGTH: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, set_cycle_length)
            ],
            SET_PERIOD_LENGTH: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, set_period_length)
            ],
            SET_LAST_START: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, set_last_start)
            ],
        },
        fallbacks=[],
        allow_reentry=True,
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("stop", stop))
    app.add_handler(conv_handler)
    app.add_handler(CallbackQueryHandler(button))

    app.run_polling()


if __name__ == "__main__":
    main()
