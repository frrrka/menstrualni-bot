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

SIGN_TO_ENGLISH = {
    "Ovan": "aries",
    "Bik": "taurus",
    "Blizanac": "gemini",
    "Rak": "cancer",
    "Lav": "leo",
    "Devica": "virgo",
    "Vaga": "libra",
    "Škorpija": "scorpio",
    "Strelac": "sagittarius",
    "Jarac": "capricorn",
    "Vodolija": "aquarius",
    "Ribe": "pisces",
}

SET_CYCLE_LENGTH, SET_PERIOD_LENGTH, SET_LAST_START, SET_STAR_SIGN = range(4)

# === FAZA-SPECIFIČNE MOTIVACIONE PORUKE ===
LUTEAL_BAD_MOOD_MSGS = [
    "⚔️ Hormoni su ti spustili pritisak? Odlično. To znači da danas pobeđuješ na BIOLOGIJU, ne na snagu volje. Budi PAMETNA, a ne HEROINA. Jedan protein, jedan dobar izbor. KRAJ PRIČE.",
    "🍫 Želja za čokoladom je progesteron koji ti šapuće laži. NE NASEDAJ. Nema krivice, ali ima KONTROLE. Nadmudri ga – nesto zdravo cokoladno, pa onda pregovaraj.",
    "📉 Energija na nuli? Prihvati pad. ALI, Lutealna faza ne sme biti izgovor za kolaps. Danas radiš na MINIMUMU koji te drži u igri. Minimum je uvek veći od nule. DRŽI LINIJU.",
    "🔥 Telo traži šećer kao narkoman? Daj mu ga, ali na zdrav način. Pametni UH (batat, ovas) + vlakna. Ti biraš oružje za bolji izgled.",
    "🌪️ Osećaš haos i težinu? Znam. Ovo je prolazna oluja, ali tvoja RIZNICA rezultata mora ostati netaknuta. Ostani dosledna SVOJOM SISTEMU. Sistem pobeđuje loše raspoloženje – uvek.",
]

LUTEAL_OKAY_MOOD_MSGS = [
    "✅ 'Onako' je u lutealnoj fazi zlatna medalja. To znači da držiš KONTROLU. Sad iskoristi taj mir da pojedeš pametan obrok (protein + mast). Bez drame, bez rizika.",
    "⏸️ Nisi na 100%, ali nisi ni pala. Odlično. Ne tražimo herojski rezultat, tražimo jednu šetnju ili 15 minuta istezanja – minimalan napor, maksimalan uticaj. Završi dan u plusu.",
    "🧭 Lutealna faza te vuče dole, a ti si stabilna. To je znak da tvoj SISTEM radi. Sad samo nastavi po planu – nema komplikovanja, nema izmišljanja. Drži ritam i telo će ti biti zahvalno sutra.",
]

LUTEAL_NUTRITION = [
    "U lutealnoj glad raste – fokus na zdrave proteine i zdrave masti: Sejk, jaja, avokado, losos... Manje UH, više zasićenja.",
    "Ako te vuče na slatko – prvo SEJK ili uzine (grčki jogurt sa bademima), pa tek onda mali komad čokolade.",
    "Pij puno vode – natečenost je često dehidracija u lutealnoj. Dodaj magnezijum ako imaš.",
]

FOLIKULAR_BAD_MOOD_MSGS = [
    "🛑 Težak dan u Folikularnoj? To je ZASTOJ. Telo ti je dalo zeleno svetlo, a ti si stala. Ne krivimo te, ali ne smeš ni da traćiš energiju. Danas nema guranja PR-a, ali ima 'odrade'. Odradi bar pola treninga ili 30 min šetnje – NE PREGOVARAJ sa rutinom.",
    "⚠️ San, stres, ili si propustila protein? Ne traži izgovore, traži REŠENJE. Folikularna faza oprašta greške, ali ne i NEAKTIVNOST. Danas je cilj da se vratiš na stazu pre nego što momentum umre. Uradi jedan mali korak koji te vraća u 🚀 Build Fazu.",
]

FOLIKULAR_OKAY_MOOD_MSGS = [
    "🔥 'Onako' u Folikularnoj je izgubljen potencijal! Ovo je prozor za tvoj najbrži napredak. Ne dozvoli da ti dan bude prosečan. Ubaci 10% više u trening ili dodaj 5g proteina u obrok. Tražimo PROGRES, ne prosek!",
    "🚀 Uskoro ćeš leteti? NE USKORO. LETI DANAS. Telo ti signalizira rast. Drži rutinu, ali dodaj mali 'boost' – to je tvoja investicija u Ovulaciju. Nema odlaganja akcije, Build Faza se ne čeka!",
]

OVULATION_BAD_MOOD_MSGS = [
    "🚨 PEAK FAZA JE! Telo ti je na 100%, a glava je umorna? To nije ciklus, to je sabotaža (Stres? San? Kofein?). Ne gubi najjači dan u ciklusu. **ODMAH resetuj.** Lagani kardio, duboko disanje, stabilan obrok. Ne dozvoli spoljnim faktorima da ti ukradu snagu.",
    "🚫 Ovulacija je tvoj prozor za PR (lični rekord), a ti si 'spuštenih ručica'? TO JE NEDOPUSTIVO. Ti imaš energiju. Ako je dan težak, to je mentalna barijera. Pročisti glavu. Uradi bilo šta što signalizira POBEDU (brzi trening snage). TI KONTROLIŠEŠ.",
]

MENSTRUAL_BAD_MOOD_MSGS = [
    "🛌 **Recovery Faza je AKTIVAN proces.** Ako je dan težak, ne padaš u krevet, već strateški biraš oporavak. Prioritet: Kvalitetan san, magnezijum i hrana bogata gvožđem. NE ŽRTVE, već FOKUS na regeneraciju. Sutra je Build Faza bliže.",
    "💧 Grčevi i umor signaliziraju da se telo ČISTI. Ne forsiraj trening, forsiraj HIDRATACIJU i NEŽNOST. Tvoj zadatak je da mu maksimalno olakšaš izbacivanje toksina. Topao čaj i lagana joga su TVOJ TRENING danas. Isključi krivicu i uključi pamet.",
]

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
        "Evo kako mozes da ih aktiviras i preuzmes kontrolu nad svojim osecanjima.\n\n"
        "Izaberi po jednu stavku uz svaku sekciju hormona i imas najbolji dan ikada 💪😊\n\n"
        "🔋 DOPAMIN, hormon zadovoljstva\n"
        "Kvalitetan san 😴 Omiljenu muziku 🎧 Fizicku aktivnost 🏃‍♂️\n\n"
        "😊 SEROTONIN, hormon srece\n"
        "Zahvalnost 🙏 Promeni okruzenja 🌿 Ostvarivanju ciljeva 🎯\n\n"
        "💖 OKSITOCIN, hormon blazenstva\n"
        "Molitvu ili meditaciju 🧘‍♀️ Velikodusnost 🎁 Grljenje 🤗\n\n"
        "🎉 ENDORFIN, hormon uzivanja\n"
        "Smeh 😂 Seks ❤️ Druzenje i ples 💃🕺\n\n"
        "Nemoj cekati da se osecas bolje, preuzmi stvar u svoje ruke 💥"
    )

# === PRAVI HOROSKOP – Ohmanda API ===
def fetch_real_horoscope(star_sign: Optional[str]) -> str:
    if not star_sign:
        return "🔮 Horoskop\nAko hoces horoskop u poruci, podesi znak u Podesi ciklus."
    
    english_sign = SIGN_TO_ENGLISH.get(star_sign)
    if not english_sign:
        return "🔮 Horoskop trenutno nije dostupan."
    
    try:
        url = f"https://ohmanda.com/api/horoscope/{english_sign}/"
        resp = requests.get(url, timeout=8)
        if resp.status_code == 200:
            data = resp.json()
            horoscope_text = data.get("horoscope", "").strip()
            if horoscope_text:
                return f"🔮 Horoskop za {star_sign}\n\n{horoscope_text}"
    except Exception as e:
        logger.warning(f"Greska pri fetch-ovanju horoskopa: {e}")
    
    fallback = [
        f"🔮 Horoskop\nZa {star_sign}, danas jedna mala odluka pravi razliku, preseci i zavrsi.",
        f"🔮 Horoskop\nZa {star_sign}, fokus na zavrsavanje obaveza, jedna stvar manje u glavi.",
        f"🔮 Horoskop\nZa {star_sign}, manje buke, vise mira, danas ti mir vredi najvise.",
        f"🔮 Horoskop\nZa {star_sign}, kreativnost ti radi, pretvori to u konkretnu akciju.",
    ]
    return random.choice(fallback)

def daily_horoscope(star_sign: Optional[str]) -> str:
    return fetch_real_horoscope(star_sign)

# === Akcioni blokovi po fazama ===
def action_block_menstrual() -> str:
    return (
        "🛌 *Recovery faza – Oporavak*\n\n"
        "🏋️ **Trening:** Šetnja, istezanje ili joga.\n"
        "🥗 **Ishrana:** Topli obroci /slatki sejkovi, gvožđe, magnezijum, zdrav kofein.\n"
        "🎯 **Danas zadatak:** Odmor bez griže savesti.\n"
    )

def action_block_follicular() -> str:
    return (
        "🚀 *Build faza – Energija raste*\n\n"
        "🏋️ **Trening:** Snaga ili intenzivan kardio. Guraj malo jače ovih dana.\n"
        "🥗 **Ishrana:** Protein + UH pre treninga. Jako gorivo = jak rezultat.\n"
        "🎯 **Danas zadatak:** Uradi trening koji si odlagala.\n"
    )

def action_block_ovulation() -> str:
    return (
        "🔥 *Peak faza – Maksimum*\n\n"
        "🏋️ **Trening:** Najjači trening, Snaga ili HIIT.\n"
        "🥗 **Ishrana:** Dovoljno kalorija i UH posle treninga.\n"
        "🎯 **Danas zadatak:** Iskoristi energiju, bez odlaganja. AKCIJA!\n"
    )

def action_block_luteal() -> str:
    return (
        "⚖️ *Maintain faza – Održavanje uz pametan pristup*\n\n"
        "🏋️ **Trening:** Lakša snaga, fokus na tehniku. 30–45 min + lagana šetnja.\n"
        "🥗 **Ishrana:** Protein u svakom obroku, dodaj zdrave masti. Manje brzih UH, Puno vlakana, zdrav kofein.\n"
        "💊 **Bonus:** Magnezijum uveče, voda češće.\n"
        "🎯 **Danas zadatak:** Bez grickanja.\n"
    )

# === Health server, keyboards, parse_date, calc_next_dates, get_cycle_state_for_today, fetch_weather_category, weather_part, phase_part, streak_prefix – sve isto ===

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

# === build_today_overview – glavni pregled (dnevna poruka i "Trenutni dan") ===
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

# === NOVO: build_mood_message – pametan, prilagođen raspoloženju ===
def build_mood_message(user: dict, mood_key: str) -> str:
    day_of_cycle, phase = get_cycle_state_for_today(user)
    weather_cat, _ = fetch_weather_category()
    prefix = streak_prefix(user)

    # Zajednički header
    header = (
        f"🧠 Tvoj feedback za danas\nDanas je {day_of_cycle}. dan ciklusa – **{phase.capitalize()}**\n\n"
        f"{prefix}"
        f"{weather_part(weather_cat)}"
        f"{phase_part(phase)}"
        f"{daily_horoscope(user.get('star_sign'))}\n\n"
    )

    # Akcioni blok (uvek prisutan, ali pozicija zavisi od raspoloženja)
    if "menstrualna" in phase:
        action_block = action_block_menstrual()
    elif "folikularna" in phase:
        action_block = action_block_follicular()
    elif "ovulacija" in phase:
        action_block = action_block_ovulation()
    else:
        action_block = action_block_luteal()

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
    else:
        okay_msgs = ["U menstrualnoj si, a dan 'onako'? To je pobeda. Telo se regeneriše, ti držiš stabilnost."]
        bad_msgs = MENSTRUAL_BAD_MOOD_MSGS
        nutrition = random.choice(GENERAL_NUTRITION)

    if mood_key == "sjajan":
        feedback = "🌟 Sjajan dan\nBravo. Zapamti sta je radilo i ponovi sutra – hormoni su ti saveznici danas."
        # Akcioni blok na kraju – kao podsetnik
        return header + feedback + f"\n\n{action_block}" + "\n\n🤍 Hvala ti sto si prijavila dan."

    elif mood_key == "onako":
        feedback = random.choice(okay_msgs)
        extra = f"\n\n✅ Mali plus za kraj dana\nIshrana: {nutrition}"
        # Akcioni blok na kraju
        return header + feedback + extra + f"\n\n{action_block}" + "\n\n🤍 Hvala ti sto si prijavila dan."

    else:  # težak ili stresan
        feedback = random.choice(bad_msgs)
        extra = f"\n\n💥 Brzi reset\nIshrana: {nutrition}\n\n{hormone_hack_block()}"
        # AKCIONI BLOK PRVO – korisnica odmah vidi REŠENJE
        return header + f"{action_block}\n\n{feedback}" + extra + "\n\n🤍 Hvala ti sto si prijavila dan."

# === Ostatak koda (update_streak, daily22_job, handlers, main) – identičan prethodnom ===

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
        await query.edit_message_text(text, parse_mode="Markdown", reply_markup=main_menu_keyboard())
        return

    if data == "today":
        text = build_today_overview(user) + "\n\nKako ti je prosao dan? Izaberi najblizu opciju:"
        await query.edit_message_text(text, parse_mode="Markdown", reply_markup=mood_keyboard())
        return

    # status i ostalo isto...

# main() i sve ostalo – identično

if __name__ == "__main__":
    main()
