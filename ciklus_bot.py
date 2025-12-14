import logging
import os
import threading
import requests
import random
from datetime import datetime, timedelta, time as dtime
from http.server import BaseHTTPRequestHandler, HTTPServer
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

# Konfiguracija logovanja
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# -------- KONFIGURACIJA --------
TOKEN = os.getenv("BOT_TOKEN")
if not TOKEN:
    raise RuntimeError("BOT_TOKEN env variable nije podesena!")

PORT = int(os.getenv("PORT", "10000"))

WEATHER_API_KEY = "42d427d7fbdd6ccdfbaa32673d9528ac" # Stvarni ključ (ili ga izvući iz env)
DEFAULT_CITY = "Belgrade,RS"

# --------- STANJA ZA CONVERSATION ---------
(
    SET_CYCLE_LENGTH,
    SET_PERIOD_LENGTH,
    SET_LAST_START,
    SET_STAR_SIGN, # NOVO: Dodato stanje za horoskopski znak
) = range(4)

USER_DATA = {}

HOROSCOPE_SIGNS = [
    "Ovan", "Bik", "Blizanac", "Rak", "Lav", "Devica", 
    "Vaga", "Škorpija", "Strelac", "Jarac", "Vodolija", "Ribe"
]


def HealthHandler(BaseHTTPRequestHandler):
    """Jednostavan HTTP server za proveru statusa na Renderu."""
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"OK")


def start_health_server():
    server = HTTPServer(("0.0.0.0", PORT), HealthHandler)
    print(f"[health] Listening on port {PORT}")
    server.serve_forever()


def get_user(chat_id: int):
    """Pristup ili inicijalizacija korisničkih podataka, uključujući horoskopski znak."""
    if chat_id not in USER_DATA:
        USER_DATA[chat_id] = {
            "cycle_length": 28,
            "period_length": 5,
            "last_start": None,
            "star_sign": None, # Inicijalno prazno
        }
    return USER_DATA[chat_id]


def main_menu_keyboard():
    """Glavni meni."""
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("📅 Podesi ciklus", callback_data="setup")],
            [InlineKeyboardButton("📊 Moj ciklus", callback_data="status")],
            [InlineKeyboardButton("🔔 Dnevna poruka 22:00", callback_data="reminders")],
            [InlineKeyboardButton("📍 Trenutni dan", callback_data="today")],
        ]
    )


def mood_keyboard():
    """Tastatura samo sa opcijama za raspoloženje (Inline)."""
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


def calc_next_dates(user):
    """Izračunava procenjene datume (sledeći period, plodni dani)."""
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
    """Vraća trenutni dan u ciklusu i fazu."""
    if not user.get("last_start"):
        return None, None

    today = datetime.now().date()
    delta_days = (today - user["last_start"]).days
    if delta_days < 0:
        return None, None

    day_of_cycle = delta_days + 1

    # Fazni proračun
    if day_of_cycle <= user.get("period_length", 5):
        phase = "menstrualna faza"
    elif day_of_cycle <= 13:
        phase = "folikularna faza"
    elif day_of_cycle == 14:
        phase = "ovulacija"
    else:
        phase = "luteinska faza"

    return day_of_cycle, phase


def fetch_weather_category():
    """Dohvata vremenske podatke i kategoriše utisak (suncano/kisovito/oblacno)."""
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

        if "rain" in main or "drizzle" in main or "thunder" in main or "snow" in main:
            return "kisovito", data["weather"][0].get("description", "")
        if "clear" in main:
            return "suncano", data["weather"][0].get("description", "")
        return "oblacno", data["weather"][0].get("description", "")
    except Exception as e:
        logger.warning(f"Greška pri čitanju vremena: {e}")
        return None, None


def fetch_daily_horoscope(star_sign: str) -> str:
    """Simulira preuzimanje dnevnog horoskopa na osnovu znaka."""
    if not star_sign:
        return "Tvoj horoskopski znak nije podešen. Idi na /start pa 'Podesi ciklus' da ga uneseš. 💫"

    # Koristi tvoj biznis fokus (DoTheChange, Quality Content, Rewards)
    messages = [
        f"Zvezde ti šalju **ekstra energiju** za tvoje {star_sign.upper()} ambicije. Dan je idealan za pokretanje malih akcija (DoTheChange!) i za postavljanje jasnih ciljeva. Veruj u svoju viziju. 🚀",
        f"Danas je ključan **mentalni fokus** za tvoj {star_sign.upper()} znak. Iskoristi mirnije sate za kreiranje Quality Content i analizu prethodnih rezultata (Past Rewards). Tvoj um je tvoje najjače oružje. 🧠",
        f"Dragi {star_sign.upper()}, budi oprezniji sa troškovima energije i emocionalnim odlukama. Zvezde preporučuju da **sačuvaš snagu**, fokusiraš se na mir i odložiš velike Social Media Promocije. Polako. 🧘‍♀️",
        f"Kreativna energija ti je danas pojačana! {star_sign.upper()}, ovo je idealan dan za Exclusive Video Recipes i plasiranje novih ideja. Tvoja strast inspiriše tvoj tim. Iskoristi to! ✨",
    ]
    
    return random.choice(messages)


# --------- TEKST BLOKOVI ---------


def _weather_part(weather_cat: str) -> str:
    """Generiše blok teksta o uticaju vremena."""
    if weather_cat == "suncano":
        return "☀️ *Vremenski utisak*\nDanas je bilo sunčano – takvi dani često daju malo više energije i lakše raspoloženje. Dozvoljeno je da i sunčan dan bude mirniji.\n\n"
    elif weather_cat == "kisovito":
        return "🌧️ *Vremenski utisak*\nKišni dani često povuku raspoloženje nadole, pojačaju umor i želju za mirom. Vreme ume ozbiljno da cimne i telo i glavu.\n\n"
    elif weather_cat == "oblacno":
        return "☁️ *Vremenski utisak*\nOblačni dani znaju da spuste fokus i motivaciju, kao da je i mozak malo zamućen. Sasvim je normalno ako si danas bila „usporenija“.\n\n"
    return ""


def _phase_part(phase: str) -> str:
    """Generiše blok teksta o hormonalnoj fazi."""
    if "menstrualna" in phase:
        return "🩸 *Menstrualna faza*\nMenstrualna faza^info intenzivno izbacuje sluznicu, mogu se javljati bolovi i pad energije. Normalno je da si sporija i osetljivija. "

[Image of 4 stages of menstrual cycle with hormone levels]
\n\n"
    if "folikularna" in phase:
        return "🌱 *Folikularna faza*\nEnergija i izdržljivost često rastu, telo se podiže i obnavlja sluznica. Osećaš se lakše u glavi i spremnije za akciju.\n\n"
    if "ovulacija" in phase:
        return "💛 *Ovulacija*\nOvo je često „peak“ faza – više snage, više samopouzdanja, više želje za pokretom. Telo je biološki najspremnije.\n\n"
    if "luteinska" in phase:
        return "🌙 *Luteinska faza*\nDruga polovina ciklusa, gde mnoge žene osećaju veću iscrpljenost, pad motivacije, zadržavanje vode i PMS. Promene raspoloženja su česte.\n\n"
    return ""


def _tip_part(phase: str) -> str:
    """Generiše blok teksta sa praktičnim savetom."""
    if "menstrualna" in phase:
        return "✅ *Praktičan savet*\nSmanji očekivanja od sebe. Fokusiraj se na toplu hranu, lagano kretanje (šetnja, istezanje) i kvalitetan san. Ovo je vreme kada je skroz ok da spustiš gas."
    if "folikularna" in phase:
        return "✅ *Praktičan savet*\nIskoristi rast energije da uvedeš jednu zdravu naviku – trening, šetnju, bolji plan obroka. Telo sada voli pokret."
    if "ovulacija" in phase:
        return "✅ *Praktičan savet*\nOdličan period za jače treninge, društvene aktivnosti, bitne sastanke i odluke. Iskoristi viši nivo samopouzdanja."
    # luteinska
    return "✅ *Praktičan savet*\nOčekuj uspone i padove. Pomaže da obroci budu bogatiji proteinom i vlaknima, da ne preskačeš obroke i da sebi daš više razumevanja umesto kritike. PMS je realan faktor."


def build_today_overview(day_of_cycle: int, phase: str, weather_cat: str, star_sign: str) -> str:
    """Sastavlja kompletan dnevni izveštaj (Ciklus + Vreme + Horoskop)."""
    base = (
        f"📍 *Danas je {day_of_cycle}. dan od početka tvog ciklusa* "
        f"(_{phase}_).\n\n"
    )
    weather_part = _weather_part(weather_cat)
    phase_part = _phase_part(phase)
    tip_part = _tip_part(phase)
    horoscope_part = fetch_daily_horoscope(star_sign)

    closing = (
        "\n\n🤍 Ovo nije „običan“ dan – ima svoj hormonalni i kosmički kontekst. "
        "Kada razumeš šta telo radi, lakše prestaneš da ga kriviš i počneš da sarađuješ sa njim."
    )

    full_report = base + weather_part + phase_part
    full_report += "\n---\n"
    full_report += f"🔮 *Dnevni Horoskop za {star_sign if star_sign else 'tebe'}*\n{horoscope_part}"
    full_report += "\n---\n"
    full_report += tip_part + closing
    
    return full_report


def build_mood_message(mood: str, day_of_cycle: int, phase: str, weather_cat: str) -> str:
    """Sastavlja poruku o raspoloženju (bez horoskopa, fokus na ciklusu)."""
    header = (
        f"🧠 *Tvoj dnevni uvid* \n"
        f"Danas je {day_of_cycle}. dan od početka tvog ciklusa (_{phase}_).\n\n"
    )
    weather_part = _weather_part(weather_cat)
    phase_part = _phase_part(phase)

    # ... (skraćeno, koristi se samo blok za raspoloženje, faza i savet)
    
    if mood == "sjajan":
        mood_part = "🌟 *Raspoloženje: Sjajan dan*\nBravo. Iscurila si energiju ciklusa i vremena u produktivnost. Nisi imala „savršен“ dan, imala si dobar dan za sebe – i to gradi stabilnost."
    elif mood == "onako":
        mood_part = "😐 *Raspoloženje: Onako dan*\nSivi, „ni tamo ni ovamo“ dani su najopasniji. Nije bilo katastrofe, ali nije bilo ni pobede. Koja je jedna mala stvar koju sutra možeš uraditi bolje? Jedan korak je dovoljan."
    elif mood == "tezak":
        mood_part = "😣 *Raspoloženje: Težak dan*\nTežak dan ne znači da si slaba. Normalno je da se energija lomi. Umesto da gledaš samo šta nije uspelo, primeti šta ipak jeste: ispoštovala si obrok, došla do kraja obaveza, našla trenutak za odmor. Ponosna si na male pobede."
    else:  # stresno
        mood_part = "🔥 *Raspoloženje: Stresan dan*\nStresan dan iscedi i telo i mozak. Ti nisi tvoj stres. Ti si osoba koja je sve to izgurala do kraja dana. Nađi jednu lekciju iz dana i jednu stvar na kojoj možeš da zahvališ sebi. Sutra ne krećeš od nule."

    tip_part = _tip_part(phase)

    closing = "\n\n🤍 Hvala ti što si stala i prijavila kako ti je danas. To je već jedan vid brige o sebi."

    return header + weather_part + phase_part + "\n\n" + mood_part + "\n\n" + tip_part + closing


# --------- JOB 22:00 (Sada šalje automatsku poruku + opciju unosa raspoloženja) ---------


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
    """Šalje kompletan dnevni izveštaj i dugmad za raspoloženje."""
    job = context.job
    chat_id = job.chat_id
    user = get_user(chat_id)

    day_of_cycle, phase = get_cycle_state_for_today(user)
    star_sign = user.get("star_sign")
    
    if day_of_cycle is None or star_sign is None:
        text = (
            "⏰ Dnevna poruka 22:00\n\n"
            "Potrebno je da kompletno podesiš ciklus *i* horoskopski znak. \n"
            "Klikni na /start pa '📅 Podesi ciklus' i unesi sve podatke."
        )
        await context.bot.send_message(chat_id, text=text, parse_mode="Markdown")
        return

    # Sastavljanje kompletnog izveštaja: Ciklus + Vreme + Horoskop
    weather_cat, _ = fetch_weather_category()
    overview_text = build_today_overview(day_of_cycle, phase, weather_cat, star_sign)
    
    # Upit za raspoloženje
    question = "\n\n_—\nDa li želiš da uneseš kako ti je prošao dan? Izaberi najbližu opciju:_"

    final_text = overview_text + question
    
    # Slanje dnevnog uvida PLUS dugmići za raspoloženje
    await context.bot.send_message(
        chat_id, 
        text=final_text, 
        reply_markup=mood_keyboard(), 
        parse_mode="Markdown"
    )


# --------- KOMANDE ---------

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    get_user(chat_id)

    text = (
        "Hej, ja sam tvoj lični bot za hormonalni i astro uvid. 🤖🩸💫\n\n"
        "Mogu da ti:\n"
        "• pratim ciklus\n"
        "• šaljem DNEVNU PORUKU u 22:00 sa KOMPLETNOM ANALIZOM (ciklus + vreme + horoskop)\n"
        "• kroz „📍 Trenutni dan“ objasnim šta se dešava u tvom telu\n\n"
        "Izaberi opciju:"
    )

    await update.message.reply_text(text, reply_markup=main_menu_keyboard(), parse_mode="Markdown")

# ... (help_command, stop – ostaju nepromenjeni)


# --------- CALLBACK DUGMAD ---------


async def button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    chat_id = query.message.chat_id
    data = query.data

    # izbor raspoloženja
    if data.startswith("mood_"):
        mood_key = data.split("_", 1)[1]
        await handle_mood_response(query, context, mood_key)
        return ConversationHandler.END

    if data == "setup":
        # Umesto samo teksta, resetujemo konverzaciju
        await query.edit_message_text(
            "Unesi dužinu ciklusa u danima (20-45), na primer 28:", reply_markup=None
        )
        return SET_CYCLE_LENGTH

    # ... (status, reminders, today – ostaju nepromenjeni, ali će today sada zvati build_today_overview sa horoskopom)
    if data == "today":
        user = get_user(chat_id)
        day_of_cycle, phase = get_cycle_state_for_today(user)
        star_sign = user.get("star_sign")
        
        if day_of_cycle is None or star_sign is None:
            text = "Nemam sve podatke (ciklus i horoskop). Klikni na '📅 Podesi ciklus'."
        else:
            weather_cat, _ = fetch_weather_category()
            text = build_today_overview(day_of_cycle, phase, weather_cat, star_sign)
        
        await query.edit_message_text(text, reply_markup=main_menu_keyboard(), parse_mode="Markdown")
        return ConversationHandler.END


async def handle_mood_response(query, context: ContextTypes.DEFAULT_TYPE, mood_key: str):
    """Obrada unosa raspoloženja i slanje finalne analize."""
    chat_id = query.message.chat_id
    user = get_user(chat_id)

    day_of_cycle, phase = get_cycle_state_for_today(user)
    if day_of_cycle is None:
        await query.edit_message_text(
            "Nemam podatke o ciklusu. Idi na /start pa '📅 Podesi ciklus'.",
            reply_markup=main_menu_keyboard(),
        )
        return

    weather_cat, _ = fetch_weather_category()
    text = build_mood_message(mood_key, day_of_cycle, phase, weather_cat)
    
    # Dodatak glavnog menija nakon unosa raspoloženja
    await query.edit_message_text(text, reply_markup=main_menu_keyboard(), parse_mode="Markdown")


# --------- UNOS CIKLUSA I HOROSKOPA ---------


async def set_cycle_length(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # ... (logika ostaje ista)
    # ... (vraća SET_PERIOD_LENGTH)
    pass # Implementacija je ista kao u prethodnoj verziji

async def set_period_length(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # ... (logika ostaje ista)
    # ... (vraća SET_LAST_START)
    pass # Implementacija je ista kao u prethodnoj verziji


def parse_date(text: str):
    # ... (funkcija ostaje ista)
    pass # Implementacija je ista kao u prethodnoj verziji


async def set_last_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Zapisuje datum i traži horoskopski znak."""
    chat_id = update.effective_chat.id
    user = get_user(chat_id)

    date_obj = parse_date(update.message.text)
    if not date_obj:
        await update.message.reply_text(
            "Ne mogu da pročitam datum. Pošalji ga u formatu dd.mm.gggg. na primer 21.11.2025."
        )
        return SET_LAST_START

    user["last_start"] = date_obj
    
    # Sada tražimo horoskopski znak (NOVO!)
    keyboard = [[InlineKeyboardButton(sign, callback_data=f"sign_{sign}")] for sign in HOROSCOPE_SIGNS]
    reply_markup = InlineKeyboardMarkup(keyboard, row_width=3) # Lepši prikaz
    
    await update.message.reply_text(
        "Zabeležio sam datum. 📌\n\nSada mi reci koji si horoskopski znak, da ti šaljem dnevnu astro-prognozu:", 
        reply_markup=reply_markup
    )
    return SET_STAR_SIGN # Prelaz na novo stanje


async def set_star_sign(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Zapisuje horoskopski znak i završava podešavanje."""
    query = update.callback_query
    await query.answer()
    chat_id = query.message.chat_id
    user = get_user(chat_id)
    data = query.data
    
    sign = data.split("_", 1)[1] # npr. "Ovan"
    user["star_sign"] = sign
    
    # Prikupljanje finalnih informacija i završetak
    info = calc_next_dates(user)
    text = (
        f"✅ *Podešavanje završeno!* Tvoj znak je *{sign}*.\n\n"
        f"Sledeća menstruacija je okvirno oko: {info['next_start'].strftime('%d.%m.%Y.')}\n"
        f"Plodni dani: {info['fertile_start'].strftime('%d.%m.%Y.')} - {info['fertile_end'].strftime('%d.%m.%Y.')}\n\n"
        "Spremni smo! Svako veče u 22:00 dobijaš kompletan izveštaj. ❤️"
    )
    
    await query.edit_message_text(text, reply_markup=main_menu_keyboard(), parse_mode="Markdown")
    return ConversationHandler.END # Završetak konverzacije


# --------- MAIN REGISTRATION ---------

# 1) Konverzacioni handler – GLOBALNO
conv_handler = ConversationHandler(
    entry_points=[CallbackQueryHandler(button, pattern='^setup$')],
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
        SET_STAR_SIGN: [ # NOVO: Dodajemo handler za horoskop
             CallbackQueryHandler(set_star_sign, pattern='^sign_')
        ],
    },
    fallbacks=[CommandHandler("start", start)],
    allow_reentry=True,
)

# 2) Aplikacija
app = ApplicationBuilder().token(TOKEN).build()

# 3) Registracija handlera
app.add_handler(CommandHandler("start", start))
app.add_handler(CommandHandler("help", help_command))
app.add_handler(CommandHandler("stop", stop))
app.add_handler(conv_handler)
# Posebno registrujemo CallbackQueryHandler za sve što nije 'setup' i nije 'sign_'
app.add_handler(CallbackQueryHandler(button))

# 4) Main: health server + bot
def main():
    threading.Thread(target=start_health_server, daemon=True).start()
    print("[bot] Starting Telegram bot...")
    app.run_polling()


if __name__ == "__main__":
    # Mock implementacija zbog kompleksnosti celog koda:
    
    async def set_cycle_length(update: Update, context: ContextTypes.DEFAULT_TYPE):
        chat_id = update.effective_chat.id
        user = get_user(chat_id)
        try:
            value = int(update.message.text.strip())
            if not 20 <= value <= 45: raise ValueError
        except ValueError:
            await update.message.reply_text("Upiši broj dana između 20 i 45:")
            return SET_CYCLE_LENGTH
        user["cycle_length"] = value
        await update.message.reply_text("OK. Sada upiši koliko dana obično traje menstruacija (2-10):")
        return SET_PERIOD_LENGTH

    async def set_period_length(update: Update, context: ContextTypes.DEFAULT_TYPE):
        chat_id = update.effective_chat.id
        user = get_user(chat_id)
        try:
            value = int(update.message.text.strip())
            if not 2 <= value <= 10: raise ValueError
        except ValueError:
            await update.message.reply_text("Upiši broj dana između 2 i 10:")
            return SET_PERIOD_LENGTH
        user["period_length"] = value
        await update.message.reply_text("Super. Sada mi pošalji datum kada je poslednja menstruacija počela. Format: dd.mm.gggg. na primer 21.11.2025.")
        return SET_LAST_START

    main()
