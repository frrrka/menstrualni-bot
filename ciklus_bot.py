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

# === FAZA-SPECIFIČNE MOTIVACIONE I NUTRICIONE PORUKE ===

# LUTEALNA FAZA – najteža, najviše pažnje
LUTEAL_BAD_MOOD_MSGS = [
    "⚔️ Hormoni su ti spustili pritisak? Odlično. To znači da danas pobeđuješ na BIOLOGIJU, ne na snagu volje. Budi PAMETNA, a ne HEROINA. Jedan protein, jedan dobar izbor. KRAJ PRIČE.",
    "🍫 Želja za čokoladom je progesteron koji ti šapuće laži. NE NASEDAJ. Nema krivice, ali ima KONTROLE. Nadmudri ga – nesto zdravo cokoladno, pa onda pregovaraj.",
    "📉 Energija na nuli? Prihvati pad. ALI, Lutealna faza ne sme biti izgovor za kolaps. Danas radiš na MINIMUMU koji te drži u igri. Minimum je uvek veći od nule. DRŽI LINIJU.",
    "🔥 Telo traži šećer kao narkoman? Daj mu ga, ali na zdrav način. Pametni UH (batat, ovas) + vlakna. Ti biraš oružje za bolji izgled.",
    "🌪️ Osećaš haos i težinu? Znam. Ovo je prolazna oluja, ali tvoja RIZNICA rezultata mora ostati netaknuta. Ostani dosledna SVOJOM SISTEMU. Sistem pobeđuje loše raspoloženje – uvek.",
]

LUTEAL_OKAY_MOOD_MSGS = [
    "✅  'Onako' je u lutealnoj fazi zlatna medalja. To znači da držiš KONTROLU. Sad iskoristi taj mir da pojedeš pametan obrok (protein + mast). Bez drame, bez rizika.",
    "⏸️ Nisi na 100%, ali nisi ni pala. Odlično. Ne tražimo herojski rezultat, tražimo jednu šetnju ili 15 minuta istezanja – minimalan napor, maksimalan uticaj. Završi dan u plusu.",
    "🧭 Lutealna faza te vuče dole, a ti si stabilna. To je znak da tvoj SISTEM radi. Sad samo nastavi po planu – nema komplikovanja, nema izmišljanja. Drži ritam i telo će ti biti zahvalno sutra.",
]

LUTEAL_NUTRITION = [
    "U lutealnoj glad raste – fokus na zdrave proteine i zdrave masti: Sejk, jaja, avokado, losos... Manje UH, više zasićenja.",
    "Ako te vuče na slatko – prvo SEJK ili uzine  (grčki jogurt sa bademima), pa tek onda mali komad čokolade.",
    "Pij puno vode – natečenost je često dehidracija u lutealnoj. Dodaj magnezijum ako imaš.",
]

# FOLIKULARNA FAZA
FOLIKULAR_BAD_MOOD_MSGS = [
    "🛑 Težak dan u Folikularnoj? To je ZASTOJ. Telo ti je dalo zeleno svetlo, a ti si stala. Ne krivimo te, ali ne smeš ni da traćiš energiju. Danas nema guranja PR-a, ali ima 'odrade'. Odradi bar pola treninga ili 30 min šetnje – NE PREGOVARAJ sa rutinom.",
    "⚠️ San, stres, ili si propustila protein? Ne traži izgovore, traži REŠENJE. Folikularna faza oprašta greške, ali ne i NEAKTIVNOST. Danas je cilj da se vratiš na stazu pre nego što momentum umre. Uradi jedan mali korak koji te vraća u 🚀 Build Fazu.",
]

FOLIKULAR_OKAY_MOOD_MSGS = [
    "🔥 'Onako' u Folikularnoj je izgubljen potencijal! Ovo je prozor za tvoj najbrži napredak. Ne dozvoli da ti dan bude prosečan. Ubaci 10% više u trening ili dodaj 5g proteina u obrok. Tražimo PROGRES, ne prosek!",
    "🚀 Uskoro ćeš leteti? NE USKORO. LETI DANAS. Telo ti signalizira rast. Drži rutinu, ali dodaj mali 'boost' – to je tvoja investicija u Ovulaciju. Nema odlaganja akcije, Build Faza se ne čeka!",
]

# OVULACIJA
OVULATION_BAD_MOOD_MSGS = [
    "🚨 PEAK FAZA JE! Telo ti je na 100%, a glava je umorna? To nije ciklus, to je sabotaža (Stres? San? Kofein?). Ne gubi najjači dan u ciklusu. **ODMAH resetuj.** Lagani kardio, duboko disanje, stabilan obrok. Ne dozvoli spoljnim faktorima da ti ukradu snagu.",
    "🚫 Ovulacija je tvoj prozor za PR (lični rekord), a ti si 'spuštenih ručica'? TO JE NEDOPUSTIVO. Ti imaš energiju. Ako je dan težak, to je mentalna barijera. Pročisti glavu. Uradi bilo šta što signalizira POBEDU (brzi trening snage). TI KONTROLIŠEŠ.",
]

# MENSTRUALNA FAZA
MENSTRUAL_BAD_MOOD_MSGS = [
    "🛌 **Recovery Faza je AKTIVAN proces.** Ako je dan težak, ne padaš u krevet, već strateški biraš oporavak. Prioritet: Kvalitetan san, magnezijum i hrana bogata gvožđem. NE ŽRTVE, već FOKUS na regeneraciju. Sutra je Build Faza bliže.",
    "💧 Grčevi i umor signaliziraju da se telo ČISTI. Ne forsiraj trening, forsiraj HIDRATACIJU i NEŽNOST. Tvoj zadatak je da mu maksimalno olakšaš izbacivanje toksina. Topao čaj i lagana joga su TVOJ TRENING danas. Isključi krivicu i uključi pamet.",
]

# GENERALNI NUTRICIONI SAVETI (za ostale faze)
GENERAL_NUTRITION = [
    "Prvo protein i povrće u obroku – stabilizuje šećer i glad.",
    "Ne preskači obroke – redovan ritam je ključ kontrole energije.",
    "Voda + dobar obrok pre nego što posegneš za grickalicama.",
]

def hormone_hack_block() -> str:
    return (
        "🤬 Nisi bas raspolozena\n\n"
        "📉 Osecas pad energije i motivacije\n\n"
        "Da li znas da mozes da hakujes svoj organizam i podignes raspolozenje na visi nivo na kvalitetan nacin 🚀🔥\n\n"
        "Nase telo je neverovatan sistem koji proizvodi pozitivne hormone, prirodne boostere srece, zadovoljstva i uzivanja.\n\n"
        "Evo kako mozes da ih aktiviras i preuzmes kontrolu nad svojim osecanjima\n"
        "Izaberi po jednu stavku uz svaku sekciju hormona i imas najbolji dan ikada 💪😊\n\n"
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

# === Akcioni blokovi po fazama ===
def action_block_menstrual() -> str:
    return (
        "🛌 **Recovery Faza – Prioritet: Oporavak i nežnost prema sebi**\n\n"
        "| Akcija         | Preporuka                              |\n"
        "|----------------|----------------------------------------|\n"
        "| **Trening**    | Lagana šetnja, joga, istezanje, pilates (20–30 min) |\n"
        "| **Intenzitet** | Veoma nizak – slušaj telo              |\n"
        "| **Fokus**      | Disanje, pokretljivost, opuštanje mišića |\n"
        "| **Ishrana**    | Hrana bogata gvožđem: spanać, meso, leblebija<br>Magnezijum: bademi, tamna čokolada |\n"
        "| **Dodatak**    | Topla kupka, čaj od kamilice, dovoljno sna |\n\n"
        "💡 Danas nije dan za rezultate – danas je dan da se telo regeneriše."
    )

def action_block_follicular() -> str:
    return (
        "🚀 **Build Faza – Energija raste, vreme za izgradnju!**\n\n"
        "| Akcija         | Preporuka                              |\n"
        "|----------------|----------------------------------------|\n"
        "| **Trening**    | Snaga (tegovi), HIIT, trčanje, grupni treninzi |\n"
        "| **Intenzitet** | Srednji do visok – iskoristi prirodni boost |\n"
        "| **Fokus**      | Mišićna masa, izdržljivost, progresija tegova |\n"
        "| **Ishrana**    | Visok protein + kompleksni ugljeni hidrati<br>Obrok pre treninga obavezan |\n"
        "| **Dodatak**    | Kreatin (po želji), beta-alanin, dobar san |\n\n"
        "💡 Ovo je tvoj prozor za najbrži napredak – iskoristi ga!"
    )

def action_block_ovulation() -> str:
    return (
        "🔥 **Peak Faza – Ti si na maksimumu!**\n\n"
        "| Akcija         | Preporuka                              |\n"
        "|----------------|----------------------------------------|\n"
        "| **Trening**    | Najteži treninzi, PR pokušaji, intenzivan kardio |\n"
        "| **Intenzitet** | Maksimalan – telo podnosi najviše      |\n"
        "| **Fokus**      | Lični rekordi, eksplozivnost, samopouzdanje |\n"
        "| **Ishrana**    | Povećan unos kalorija, više UH posle treninga |\n"
        "| **Dodatak**    | BCAA tokom treninga, dobar recovery shake |\n\n"
        "💡 Danas možeš više nego što misliš – idi all in!"
    )

def action_block_luteal() -> str:
    return (
        "⚖️ **Maintain Faza – Održavanje uz pametan pristup**\n\n"
        "| Akcija         | Preporuka                              |\n"
        "|----------------|----------------------------------------|\n"
        "| **Trening**    | Snaga sa manjim tegovima, pilates, plivanje, duže šetnje |\n"
        "| **Intenzitet** | Srednji – izbegavaj preterani stres    |\n"
        "| **Fokus**      | Tehnika, stabilnost, core, opuštanje  |\n"
        "| **Ishrana**    | Više masti i proteina, manje UH<br>Fokus na zasićenje (avokado, jaja, losos) |\n"
        "| **Dodatak**    | Magnezijum, vitamin B6, topla voda sa limunom |\n\n"
        "💡 Manje je više – čuvaj energiju, ali ostani dosledna."
    )

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
    data.setdefault("last_start", None)
    data.setdefault("star_sign", None)
    data.setdefault("seen_start", False)
    data.setdefault("bad_mood_streak", 0)
    data.setdefault("last_mood_date", None)
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
    for fmt in ["%d.%m.%Y", "%d.%m.%Y."]:
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
        return "☀️ Vremenski utisak\nSunce cesto podigne energiju, ali ne znaci da moras da guras na maksimum.\n\n"
    if weather_cat == "kisovito":
        return "🌧️ Vremenski utisak\nKisni dan ume da spusti raspolozenje i fokus, normalno je ako si usporenija.\n\n"
    if weather_cat == "oblacno":
        return "☁️ Vremenski utisak\nOblacno cesto donese tihi umor, prilagodi tempo, bez drame.\n\n"
    return ""

def phase_part(phase: str) -> str:
    if "menstrualna" in phase:
        return "🩸 Menstrualna faza\nMoguci su grcevi, pad energije, veca osetljivost, spusti gas bez krivice.\n\n"
    if "folikularna" in phase:
        return "🌱 Folikularna faza\nEnergija cesto raste, lakse se uvodi rutina i pokret.\n\n"
    if "ovulacija" in phase:
        return "💛 Ovulacija\nCesto peak faza, vise energije i samopouzdanja, dobar dan za akciju.\n\n"
    return "🌙 Luteinska faza\nCesce su natecenost, promena raspolozenja i veca glad, hormoni rade svoje.\n\n"

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

def streak_prefix(user: dict) -> str:
    streak = user.get("bad_mood_streak", 0)
    if streak >= 3:
        return "🆘 Treći dan zaredom teži dan.\nNe treba ti pritisak, treba ti stabilizacija. Danas je cilj minimum koji te drži u kontroli.\n\n"
    if streak == 2:
        return "⚠️ Drugi dan zaredom teži dan.\nNormalno je. Danas igramo pametno, ne herojski.\n\n"
    return ""

def build_today_overview(user: dict) -> str:
    day_of_cycle, phase = get_cycle_state_for_today(user)
    if day_of_cycle is None:
        return "Nemam datum poslednje menstruacije.\nUdji na Podesi ciklus i unesi datum."

    weather_cat, _ = fetch_weather_category()
    star_sign = user.get("star_sign")
    prefix = streak_prefix(user)

    if "menstrualna" in phase:
        action_block = action_block_menstrual()
    elif "folikularna" in phase:
        action_block = action_block_follicular()
    elif "ovulacija" in phase:
        action_block = action_block_ovulation()
    else:
        action_block = action_block_luteal()

    return (
        f"📍 Danas je {day_of_cycle}. dan ciklusa – **{phase.capitalize()}**\n\n"
        f"{prefix}"
        f"{weather_part(weather_cat)}"
        f"{phase_part(phase)}"
        f"{daily_horoscope(star_sign)}\n\n"
        f"{action_block}\n\n"
        "🤍 Tvoj ekskluzivni dnevni recept za transformaciju – prilagođen samo tebi i tvom ciklusu.\n"
        "Transformations nije samo trening. To je sinhronizacija sa sobom."
    )

def build_mood_message(user: dict, mood_key: str) -> str:
    day_of_cycle, phase = get_cycle_state_for_today(user)
    weather_cat, _ = fetch_weather_category()
    header = f"🧠 Tvoj dnevni uvid\nDanas je {day_of_cycle}. dan ciklusa, faza je {phase}\n\n"
    base = weather_part(weather_cat) + phase_part(phase)
    prefix = streak_prefix(user)

    # Biranje poruka po fazi
    if "luteinska" in phase:
        okay_msgs = LUTEAL_OKAY_MOOD_MSGS
        bad_msgs = LUTEAL_BAD_MOOD_MSGS
        nutrition = random.choice(LUTEAL_NUTRITION)
    elif "folikularna" in phase:
        okay_msgs = FOLIKULAR_OKAY_MOOD_MSGS
        bad_msgs = FOLIKULAR_BAD_MOOD_MSGS
        nutrition = random.choice(GENERAL_NUTRITION)
    elif "ovulacija" in phase:
        okay_msgs = ["U peak fazi si – čak i 'onako' dan je bolji nego kod drugih u lošijoj fazi. Iskoristi snagu."]
        bad_msgs = OVULATION_BAD_MOOD_MSGS
        nutrition = random.choice(GENERAL_NUTRITION)
    else:  # menstrualna
        okay_msgs = ["U menstrualnoj si, a dan 'onako'? To je pobeda. Telo se regeneriše, ti držiš stabilnost."]
        bad_msgs = MENSTRUAL_BAD_MOOD_MSGS
        nutrition = random.choice(GENERAL_NUTRITION)

    if mood_key == "sjajan":
        mood_text = "🌟 Sjajan dan\nBravo. Zapamti sta je radilo i ponovi sutra – hormoni su ti saveznici danas."
        extra = ""
    elif mood_key == "onako":
        mood_text = random.choice(okay_msgs)
        extra = f"\n\n✅ Mali plus za kraj dana\nIshrana: {nutrition}"
    else:  # težak ili stresan
        mood_text = random.choice(bad_msgs)
        extra = f"\n\n💥 Brzi reset\nIshrana: {nutrition}\n\n{hormone_hack_block()}"

    closing = "\n\n🤍 Hvala ti sto si prijavila dan."
    return header + prefix + base + f"\n{mood_text}" + extra + closing

def update_streak(user: dict, mood_key: str):
    today = datetime.now(TZ).date()
    last_date = user.get("last_mood_date")

    if last_date != today:
        user["bad_mood_streak"] = 0

    if mood_key == "sjajan":
        user["bad_mood_streak"] = 0
    else:
        user["bad_mood_streak"] = user.get("bad_mood_streak", 0) + 1

    user["last_mood_date"] = today

async def daily22_job(context: ContextTypes.DEFAULT_TYPE):
    job = context.job
    chat_id = job.chat_id
    stored = context.application.chat_data.get(chat_id)
    if not stored:
        await context.bot.send_message(
            chat_id=chat_id,
            text="⏰ 22:00 poruka\nNemam tvoje podatke, udji na /start i podesi ciklus.",
        )
        return

    overview = build_today_overview(stored)
    text = (
        "⏰ Dnevna poruka 22:00\n\n"
        f"{overview}\n\n"
        "Kako ti je prosao dan? Izaberi najblizu opciju:"
    )
    await context.bot.send_message(
        chat_id=chat_id,
        text=text,
        parse_mode="Markdown",
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
        "Hej, ja sam bot za ciklus, vreme, horoskop i raspolozenje. 🤖🩸\n\n"
        "Svako vece u 22:00 dobijas poruku automatski.\n"
        "Izaberi opciju:",
        reply_markup=main_menu_keyboard(),
    )

async def cancel_setup(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Podešavanje otkazano.", reply_markup=main_menu_keyboard())
    return ConversationHandler.END

async def setup_entry(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    ensure_user_defaults(context)
    await query.edit_message_text("Unesi duzinu ciklusa u danima (20–45), npr. 28:")
    return SET_CYCLE_LENGTH

async def set_cycle_length(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = ensure_user_defaults(context)
    try:
        value = int(update.message.text.strip())
        if not 20 <= value <= 45:
            raise ValueError
    except ValueError:
        await update.message.reply_text("Molim te, upisi broj između 20 i 45.")
        return SET_CYCLE_LENGTH
    user["cycle_length"] = value
    await update.message.reply_text("Ok. Koliko dana traje menstruacija (2–10), npr. 5?")
    return SET_PERIOD_LENGTH

async def set_period_length(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = ensure_user_defaults(context)
    try:
        value = int(update.message.text.strip())
        if not 2 <= value <= 10:
            raise ValueError
    except ValueError:
        await update.message.reply_text("Molim te, upisi broj između 2 i 10.")
        return SET_PERIOD_LENGTH
    user["period_length"] = value
    await update.message.reply_text("Super. Pošalji datum poslednje menstruacije (dd.mm.yyyy), npr. 21.11.2025.")
    return SET_LAST_START

async def set_last_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = ensure_user_defaults(context)
    date_obj = parse_date(update.message.text)
    today = datetime.now(TZ).date()

    if not date_obj:
        await update.message.reply_text("Ne mogu da pročitam datum. Probaj format: 21.11.2025.")
        return SET_LAST_START

    if date_obj > today:
        await update.message.reply_text("Datum ne može biti u budućnosti. 😅")
        return SET_LAST_START

    if (today - date_obj).days > 90:
        await update.message.reply_text("Datum je previše star. Unesi poslednju menstruaciju iz poslednja 3 meseca.")
        return SET_LAST_START

    user["last_start"] = date_obj
    user["bad_mood_streak"] = 0
    await update.message.reply_text(
        "Zabeleženo. Sada izaberi horoskopski znak ili preskoči.",
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
    sign_txt = user["star_sign"] if user["star_sign"] else "nije podešeno"
    text = "✅ Podešavanje završeno!\n\n"
    if info:
        text += (
            f"Znak: {sign_txt}\n"
            f"Sledeća menstruacija oko: {info['next_start'].strftime('%d.%m.%Y.')}\n"
            f"Plodni dani: {info['fertile_start'].strftime('%d.%m.%Y.')} – {info['fertile_end'].strftime('%d.%m.%Y.')}\n\n"
        )
    text += "Svako veče u 22:00 stiže dnevna poruka automatski."
    await query.edit_message_text(text, reply_markup=main_menu_keyboard())
    return ConversationHandler.END

async def cb_router(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user = ensure_user_defaults(context)
    data = query.data

    if data.startswith("mood_"):
        mood_key = data.split("_", 1)[1]
        if not user.get("last_start"):
            await query.edit_message_text(
                "Nemam datum poslednje menstruacije.\nUdji na Podesi ciklus i unesi datum.",
                reply_markup=main_menu_keyboard(),
            )
            return

        update_streak(user, mood_key)
        text = build_mood_message(user, mood_key)
        await query.edit_message_text(text, reply_markup=main_menu_keyboard())
        return

    if data == "status":
        info = calc_next_dates(user)
        if not user.get("last_start"):
            text = "Nemam datum poslednje menstruacije. Udji na Podesi ciklus i unesi datum."
        else:
            text = (
                "📊 Trenutne postavke\n\n"
                f"Duzina ciklusa: {user['cycle_length']} dana\n"
                f"Trajanje menstruacije: {user['period_length']} dana\n"
                f"Poslednji pocetak: {user['last_start'].strftime('%d.%m.%Y.')}\n"
                f"Znak: {user['star_sign'] if user.get('star_sign') else 'nije podešeno'}\n"
            )
            if info:
                text += (
                    "\n📆 Procene\n"
                    f"Sledeća menstruacija oko: {info['next_start'].strftime('%d.%m.%Y.')}\n"
                    f"Plodni dani: {info['fertile_start'].strftime('%d.%m.%Y.')} – {info['fertile_end'].strftime('%d.%m.%Y.')}\n"
                    f"Kraj tekuće menstruacije: {info['period_end'].strftime('%d.%m.%Y.')}\n"
                )
        await query.edit_message_text(text, reply_markup=main_menu_keyboard())
        return

    if data == "today":
        overview = build_today_overview(user)
        text = (
            f"{overview}\n\n"
            "Kako ti je prosao dan? Izaberi najblizu opciju:"
        )
        await query.edit_message_text(text, parse_mode="Markdown", reply_markup=mood_keyboard())
        return

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    logger.exception("Unhandled error", exc_info=context.error)

async def post_init(application):
    jq = application.job_queue
    if jq is None:
        return
    for chat_id, data in list(application.chat_data.items()):
        try:
            if not isinstance(chat_id, int) or not isinstance(data, dict):
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
        fallbacks=[
            CommandHandler("cancel", cancel_setup),
            CommandHandler("start", start),
        ],
        allow_reentry=True,
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(conv_handler)
    app.add_handler(CallbackQueryHandler(cb_router))
    app.add_error_handler(error_handler)

    print("[bot] Starting Telegram bot...")
    app.run_polling()

if __name__ == "__main__":
    main()
