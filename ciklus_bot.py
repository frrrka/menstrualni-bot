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
    "🛌 <b>Recovery Faza je AKTIVAN proces.</b> Ako je dan težak, ne padaš u krevet, već strateški biraš oporavak. Prioritet: Kvalitetan san, magnezijum i hrana bogata gvožđem. NE ŽRTVE, već FOKUS na regeneraciju. Sutra je Build Faza bliže.",
    "💧 Grčevi i umor signaliziraju da se telo ČISTI. Ne forsiraj trening, forsiraj HIDRATACIJU i NEŽNOST. Tvoj zadatak je da mu maksimalno olakšaš izbacivanje toksina. Topao čaj i lagana joga su TVOJ TRENING danas. Isključi krivicu i uključi pamet.",
]

# === HERBALIFE SAVETI PO FAZI (opšti) ===
HL_PHASE_NUTRITION = {
    "menstrualna faza": [
        "Protein, F1 sejk + PDM, ako hoces sladje, F1 Vanilla ili Chocolate, topli napitak uz to",
        "Magnezijum, Herbalife vitamins and minerals za zene, uvece uz obrok",
        "Omega 3, Herbalifeline Max uz rucak ili veceru",
        "Caj za energiju, Herbalife caj, ali bez preterivanja, telo je u recovery modu",
    ],
    "folikularna faza": [
        "Protein boost, F1 sejk + PDM, posle treninga jos jedna merica PDM ako ti fali proteina",
        "Energija, Herbalife caj pre treninga ili ujutru, fokus i drive",
        "Vlakna, Herbalife vlakna u sejk, stabilniji apetit i manje snackovanja",
        "Omega 3, Herbalifeline Max dnevno, to je investicija u oporavak i hormonalni balans",
    ],
    "ovulacija": [
        "Peak dan, F1 sejk + PDM, plus vlakna u sejk da ne poludis od gladi posle treninga",
        "Caj, Herbalife caj, idealno pre posla ili pre treninga",
        "Vitamini i minerali za zene, drzis performans stabilnim",
        "Omega 3, Herbalifeline Max, zato sto zelis rezultat i kvalitet, ne samo kalorije",
    ],
    "luteinska faza": [
        "Kad krene glad, prvo F1 sejk + PDM, to ti je reset, pa tek onda odluka o hrani",
        "Vlakna u sejk, Herbalife vlakna, jer luteinska voli da napravi haos sa apetitom",
        "Omega 3, Herbalifeline Max, smanjujes upale i popravis osecaj u telu",
        "Vitamini i minerali za zene, plus magnezijum uvece ako imas, san i nervi prvo",
        "Caj moze, ali pametno, ako si anksiozna, smanji ili prebaci ranije u danu",
    ],
}

def hl_tip_for_phase(phase: str) -> str:
    tips = HL_PHASE_NUTRITION.get(phase, [])
    if not tips:
        return "F1 sejk + PDM za protein, Herbalife caj za energiju, vlakna u sejk za stabilnu glad, Omega 3 i vitamini dnevno."
    return random.choice(tips)

# === HERBALIFE SAVETI PO MOOD-U (2–3 proizvoda) ===
HL_MOOD_TIPS = {
    "sjajan": [
        "H24 Hydrate, voda i elektroliti, pogotovo ako si trenirala",
        "H24 CR7 Drive, pre treninga ili tokom, ako ti treba performance",
        "Rebuild Strength, posle treninga za oporavak",
        "Cell Activator, ujutru, dugoročna energija i oporavak",
        "Herbalifeline Max Omega 3, uz obrok, konsistentno svaki dan",
    ],
    "onako": [
        "F1 sejk + PDM, najbrži stabilan obrok bez razmišljanja",
        "Herbalife Vlakna u sejk, da ne krene večernje grickanje",
        "Herbal Aloe, za stomak i rutinu unosa tečnosti",
        "Herbalife čaj, ranije u danu za fokus, ne kasno uveče",
        "Vitamini i minerali za žene, dnevno, bez preskakanja",
    ],
    "tezak": [
        "F1 sejk + PDM odmah, da prekineš pad i napade gladi",
        "Herbalife Vlakna, da te zasiti i smiri apetit",
        "Herbalifeline Max Omega 3, smanjuje upalni osećaj i podiže kvalitet oporavka",
        "Magnezijum uveče, ako koristiš, san i nervi prvo",
        "Herbal Aloe, stomak i nadutost često prave lažan stres",
    ],
    "stresan": [
        "F1 sejk + PDM, stabilizuje šećer i glavu",
        "Herbalife čaj samo ranije, ako si napeta, nemoj kasno",
        "Herbalifeline Max Omega 3, nervni sistem i oporavak",
        "Vitamini i minerali za žene, podrška u periodima stresa",
        "Herbalife Vlakna, da presečeš emocionalno snackovanje",
    ],
}

def hl_mood_block(mood_key: str, phase: str) -> str:
    mood_tips = HL_MOOD_TIPS.get(mood_key, [])
    picks = random.sample(mood_tips, k=min(3, len(mood_tips))) if mood_tips else []
    phase_tip = hl_tip_for_phase(phase)
    extra = ""
    if picks:
        extra = "🥤 <b>Herbalife fokus po raspoloženju:</b>\n" + "\n".join([f"• {p}" for p in picks])
    if phase_tip:
        extra = (extra + "\n\n" if extra else "") + f"🧠 <b>Herbalife fokus po fazi:</b> {phase_tip}"
    return extra

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

# === DNEVNI HOROSKOP ZA KARIJERU I FINANSIJE (30 poruka) ===
def daily_horoscope(star_sign: Optional[str]) -> str:
    if not star_sign:
        return "🔮 Horoskop za karijeru i finansije\nAko želiš dnevni horoskop za posao i novac, podesi znak u Podesi ciklus."

    messages = [
        f"🔮 Horoskop za karijeru i finansije\nZa {star_sign}, danas je dan za pametne poslovne poteze. Fokusiraj se na sistem – jedna dosledna akcija na poslu donosi više nego 10 haotičnih. Drži ritam, rezultati dolaze.",
        f"🔮 Horoskop za karijeru i finansije\nZa {star_sign}, prilika za napredak ili dodatni prihod je blizu. Ne čekaj savršen trenutak – uradi jedan korak ka boljoj poziciji. Sistem pobeđuje sreću.",
        f"🔮 Horoskop za karijeru i finansije\nZa {star_sign}, pregledaj budžet i troškove. Mali uštedni potez danas gradi finansijsku slobodu sutra. Bez impulsivnih kupovina – disciplina je tvoja snaga.",
        f"🔮 Horoskop za karijeru i finansije\nZa {star_sign}, posao zahteva fokus na detalje. Završi obaveze bez odlaganja – jedna stvar manje u glavi znači više energije za velike karijerne ciljeve.",
        f"🔮 Horoskop za karijeru i finansije\nZa {star_sign}, vreme je za planiranje karijernog napretka. Investiraj u sebe (znanje, veštine) – to donosi najveći finansijski povrat.",
        f"🔮 Horoskop za karijeru i finansije\nZa {star_sign}, stabilnost je ključ. Izbegavaj rizik, čuvaj rezervu – neočekivane poslovne prilike dolaze onima koji su spremni.",
        f"🔮 Horoskop za karijeru i finansije\nZa {star_sign}, timski rad ili kontakt sa kolegama donosi korist. Jedan dobar razgovor može otvoriti vrata ka boljoj poziciji ili bonusu.",
        f"🔮 Horoskop za karijeru i finansije\nZa {star_sign}, novac dolazi kroz doslednost. Drži budžet, ulaži pametno – danas gradiš sigurnu finansijsku budućnost.",
        f"🔮 Horoskop za karijeru i finansije\nZa {star_sign}, prilika za promenu posla ili dodatni projekat je blizu. Pripremi se – sistem i disciplina pobeđuju konkurenciju.",
        f"🔮 Horoskop za karijeru i finansije\nZa {star_sign}, fokus na dugoročne ciljeve. Mali korak danas na poslu ili u finansijama vodi ka velikoj promeni za godinu dana.",
        f"🔮 Horoskop za karijeru i finansije\nZa {star_sign}, danas je dan za pregled prioriteta. Manje buke na poslu, više akcije – završeni zadaci donose mir i bolju zaradu.",
        f"🔮 Horoskop za karijeru i finansije\nZa {star_sign}, finansijska disciplina je tvoja najveća snaga. Ne troši na nepotrebno – svaki ušteđeni dinar je ulaganje u slobodu.",
        f"🔮 Horoskop za karijeru i finansije\nZa {star_sign}, posao teče bolje kad imaš jasan plan. Danas napravi listu prioriteta – sistemski pristup donosi brže rezultate.",
        f"🔮 Horoskop za karijeru i finansije\nZa {star_sign}, prilika za bonus ili povišicu je u detaljima. Obrati pažnju na kvalitet rada – to se uvek isplati.",
        f"🔮 Horoskop za karijeru i finansije\nZa {star_sign}, danas je dobar dan za štednju. Odloži impulsivnu kupovinu – sutra ćeš biti zahvalna sebi.",
        f"🔮 Horoskop za karijeru i finansije\nZa {star_sign}, karijerni rast dolazi kroz učenje. Danas uloži vreme u novu veštinu – to je najbolja investicija.",
        f"🔮 Horoskop za karijeru i finansije\nZa {star_sign}, finansije su stabilnije kad imaš rezervu. Danas dodaj nešto na štedni račun – mali korak, veliki mir.",
        f"🔮 Horoskop za karijeru i finansije\nZa {star_sign}, poslovni kontakt ili mreža danas može doneti korist. Ne zatvaraj vrata – jedna poruka može promeniti sve.",
        f"🔮 Horoskop za karijeru i finansije\nZa {star_sign}, danas je dan za završavanje obaveza. Čista glava = više prostora za nove poslovne prilike.",
        f"🔮 Horoskop za karijeru i finansije\nZa {star_sign}, novac ne dolazi preko noći – dolazi kroz sistem. Drži ritam, rezultati su neizbežni.",
        f"🔮 Horoskop za karijeru i finansije\nZa {star_sign}, pregledaj stare troškove. Gde curi novac? Danas zatvori tu rupu – to je najbrži način za veću zaradu.",
        f"🔮 Horoskop za karijeru i finansije\nZa {star_sign}, posao je maraton, ne sprint. Danas održi tempo – doslednost je ono što te izdvaja od drugih.",
        f"🔮 Horoskop za karijeru i finansije\nZa {star_sign}, finansijska sloboda počinje malim navikama. Danas preskoči kafu van kuće – mali potez, veliki efekat.",
        f"🔮 Horoskop za karijeru i finansije\nZa {star_sign}, danas je dan za poslovni plan. Zapiši ciljeve za naredni mesec – jasan put vodi do veće zarade.",
        f"🔮 Horoskop za karijeru i finansije\nZa {star_sign}, prilika za dodatni prihod je u tvom znanju. Danas ponudi uslugu ili ideju – ne čekaj da te neko pita.",
        f"🔮 Horoskop za karijeru i finansije\nZa {star_sign}, izbegavaj dugove i kredite ako možeš. Danas plati gotovinom – osećaj kontrole je neprocenjiv.",
        f"🔮 Horoskop za karijeru i finansije\nZa {star_sign}, karijera raste kad ulažeš u sebe. Danas pročitaj članak ili gledaj video o veštini koja ti treba.",
        f"🔮 Horoskop za karijeru i finansije\nZa {star_sign}, finansije su ogledalo navika. Danas promeni jednu lošu naviku – rezultati dolaze brže nego što misliš.",
        f"🔮 Horoskop za karijeru i finansije\nZa {star_sign}, posao danas zahteva strpljenje. Ne žuri sa odlukama – pametan potez je bolji od brzog.",
        f"🔮 Horoskop za karijeru i finansije\nZa {star_sign}, novac koji uštediš danas je novac koji radi za tebe sutra. Drži disciplinu – sloboda je na domaku.",
    ]

    return random.choice(messages)

# === Akcioni blokovi po fazama (HTML bold) ===
def action_block_menstrual() -> str:
    return (
        "🛌 <b>Recovery faza – Oporavak</b>\n\n"
        "🏋️ <b>Trening:</b> Šetnja, istezanje ili joga.\n"
        "🥗 <b>Ishrana:</b> Topli obroci /slatki sejkovi, gvožđe, magnezijum, zdrav kofein.\n"
        "🎯 <b>Danas zadatak:</b> Odmor bez griže savesti.\n"
    )

def action_block_follicular() -> str:
    return (
        "🚀 <b>Build faza – Energija raste</b>\n\n"
        "🏋️ <b>Trening:</b> Snaga ili intenzivan kardio. Guraj malo jače ovih dana.\n"
        "🥗 <b>Ishrana:</b> Protein + UH pre treninga. Jako gorivo = jak rezultat.\n"
        "🎯 <b>Danas zadatak:</b> Uradi trening koji si odlagala.\n"
    )

def action_block_ovulation() -> str:
    return (
        "🔥 <b>Peak faza – Maksimum</b>\n\n"
        "🏋️ <b>Trening:</b> Najjači trening, Snaga ili HIIT.\n"
        "🥗 <b>Ishrana:</b> Dovoljno kalorija i UH posle treninga.\n"
        "🎯 <b>Danas zadatak:</b> Iskoristi energiju, bez odlaganja. AKCIJA!\n"
    )

def action_block_luteal() -> str:
    return (
        "⚖️ <b>Maintain faza – Održavanje uz pametan pristup</b>\n\n"
        "🏋️ <b>Trening:</b> Lakša snaga, fokus na tehniku. 30–45 min + lagana šetnja.\n"
        "🥗 <b>Ishrana:</b> Protein u svakom obroku, dodaj zdrave masti. Manje brzih UH, Puno vlakana, zdrav kofein.\n"
        "💊 <b>Bonus:</b> Magnezijum uveče, voda češće.\n"
        "🎯 <b>Danas zadatak:</b> Bez grickanja.\n"
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

# --- TASTATURE ---
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

# --- KALKULATORI I UTILITY FUNKCIJE ---
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

    hl_block = hl_mood_block("onako", phase)

    return (
        f"📍 Danas je {day_of_cycle}. dan ciklusa – <b>{phase.capitalize()}</b>\n\n"
        f"{prefix}"
        f"{weather_part(weather_cat)}"
        f"{phase_part(phase)}"
        f"{daily_horoscope(star_sign)}\n\n"
        f"{action_block}\n\n"
        f"{hl_block}\n\n"
        "🤍 Tvoj ekskluzivni dnevni recept za transformaciju – prilagođen samo tebi i tvom ciklusu.\n"
        "Transformations nije samo trening. To je sinhronizacija sa sobom."
    )

def build_mood_message(user: dict, mood_key: str) -> str:
    day_of_cycle, phase = get_cycle_state_for_today(user)
    weather_cat, _ = fetch_weather_category()
    prefix = streak_prefix(user)
    header = (
        f"🧠 Tvoj feedback za danas\nDanas je {day_of_cycle}. dan ciklusa – <b>{phase.capitalize()}</b>\n\n"
        f"{prefix}"
        f"{weather_part(weather_cat)}"
        f"{phase_part(phase)}"
        f"{daily_horoscope(user.get('star_sign'))}\n\n"
    )

    if "menstrualna" in phase:
        action_block = action_block_menstrual()
    elif "folikularna" in phase:
        action_block = action_block_follicular()
    elif "ovulacija" in phase:
        action_block = action_block_ovulation()
    else:
        action_block = action_block_luteal()

    hl_block = hl_mood_block(mood_key, phase)

    if mood_key == "sjajan":
        feedback = "🌟 Sjajan dan\nBravo. Zapamti sta je radilo i ponovi sutra – hormoni su ti saveznici danas."
        return header + feedback + f"\n\n{action_block}\n\n{hl_block}" + "\n\n🤍 Hvala ti sto si prijavila dan."
    elif mood_key == "onako":
        feedback = random.choice(LUTEAL_OKAY_MOOD_MSGS if "luteinska" in phase else FOLIKULAR_OKAY_MOOD_MSGS if "folikularna" in phase else ["Dobar posao što držiš stabilnost."])
        extra = f"\n\n✅ Mali plus za kraj dana\n{hl_block}"
        return header + feedback + extra + f"\n\n{action_block}" + "\n\n🤍 Hvala ti sto si prijavila dan."
    else:
        if "luteinska" in phase:
            feedback = random.choice(LUTEAL_BAD_MOOD_MSGS)
        elif "folikularna" in phase:
            feedback = random.choice(FOLIKULAR_BAD_MOOD_MSGS)
        elif "ovulacija" in phase:
            feedback = random.choice(OVULATION_BAD_MOOD_MSGS)
        else:
            feedback = random.choice(MENSTRUAL_BAD_MOOD_MSGS)
        extra = f"\n\n💥 Brzi reset\n{hl_block}\n\n{hormone_hack_block()}"
        return header + f"{action_block}\n\n{feedback}" + extra + "\n\n🤍 Hvala ti sto si prijavila dan."

def update_streak(user: dict, mood_key: str):
    today = datetime.now(TZ).date()
    last_date = user.get("last_mood_date")
    streak = user.get("bad_mood_streak", 0)

    if last_date != today:
        if last_date is not None and (today - last_date).days > 1:
            streak = 0

        if mood_key == "sjajan":
            streak = 0
        else:
            streak = streak + 1 if last_date == today - timedelta(days=1) else 1

    user["bad_mood_streak"] = streak
    user["last_mood_date"] = today

# --- TEST KOMANDA ---
async def test22(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("OK, šaljem test dnevnu poruku sada...")
    fake_job = type("FakeJob", (), {"chat_id": update.effective_chat.id})()
    context.job = fake_job
    await daily22_job(context)

# --- DAILY JOB ---
async def daily22_job(context: ContextTypes.DEFAULT_TYPE):
    job = context.job
    chat_id = job.chat_id
    stored = context.application.chat_data.get(chat_id)

    if not stored:
        await context.bot.send_message(
            chat_id=chat_id,
            text="⏰ Večernji podsetnik\nJoš uvek nemam tvoje podatke o ciklusu. 😊\nKada podesiš, svako veče stiže personalizovana poruka!\nUdji na Podeši ciklus i krenimo! 🚀",
            parse_mode="HTML",
        )
        return

    if not stored.get("last_start"):
        await context.bot.send_message(
            chat_id=chat_id,
            text="⏰ Večernji podsetnik\nJoš uvek nemam tvoje podatke o ciklusu. 😊\nKada podesiš, svako veče stiže personalizovana poruka!\nUdji na Podeši ciklus i krenimo! 🚀",
            parse_mode="HTML",
        )
        return

    overview = build_today_overview(stored)
    text = (
        f"{overview}\n\n"
        "Kako ti je prosao dan? Izaberi najblizu opciju:"
    )

    await context.bot.send_message(
        chat_id=chat_id,
        text=text,
        parse_mode="HTML",
        reply_markup=mood_keyboard(),
    )

# --- START SA ZAKAZIVANJEM ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = ensure_user_defaults(context)
    chat_id = update.effective_chat.id
    user["seen_start"] = True

    jq = context.application.job_queue
    name = job_name_daily(chat_id)
    if jq:
        for j in jq.get_jobs_by_name(name):
            j.schedule_removal()
        jq.run_daily(
            daily22_job,
            time=dtime(hour=22, minute=0, tzinfo=TZ),
            name=name,
            chat_id=chat_id,
        )

    await update.message.reply_text(
        "Hej, ja sam bot za ciklus, vreme, horoskop i raspolozenje. 🤖🩸\n\n"
        "Svako veče u 22:00 stiže dnevna poruka automatski.\n"
        "Izaberi opciju:",
        reply_markup=main_menu_keyboard(),
    )

# --- PODEŠAVANJE HANDLERI ---
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

    chat_id = update.effective_chat.id
    jq = context.application.job_queue
    name = job_name_daily(chat_id)
    if jq:
        for j in jq.get_jobs_by_name(name):
            j.schedule_removal()
        jq.run_daily(
            daily22_job,
            time=dtime(hour=22, minute=0, tzinfo=TZ),
            name=name,
            chat_id=chat_id,
        )

    await update.message.reply_text(
        "Zabeleženo. Sada izaberi horoskopski znak ili preskoči.",
        reply_markup=sign_keyboard(),
    )
    return SET_STAR_SIGN

async def set_star_sign(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user = ensure_user_defaults(context)
    chat_id = update.effective_chat.id

    if query.data == "sign_skip":
        user["star_sign"] = None
    else:
        user["star_sign"] = query.data.split("_", 1)[1]

    jq = context.application.job_queue
    name = job_name_daily(chat_id)
    if jq:
        for j in jq.get_jobs_by_name(name):
            j.schedule_removal()
        jq.run_daily(
            daily22_job,
            time=dtime(hour=22, minute=0, tzinfo=TZ),
            name=name,
            chat_id=chat_id,
        )

    info = calc_next_dates(user)
    sign_txt = user["star_sign"] if user["star_sign"] else "nije podešeno"
    text = "✅ Podešavanje završeno!\n\n"
    if info:
        text += (
            f"Znak: {sign_txt}\n"
            f"Sledeća menstruacija oko: {info['next_start'].strftime('%d.%m.%Y.')}\n"
            f"Plodni dani: {info['fertile_start'].strftime('%d.%m.%Y.')} – {info['fertile_end'].strftime('%d.%m.%Y.')}\n\n"
        )
    text += "Svako veče u 22:00 stiže dnevna poruka automatski. 🚀"
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
        await query.edit_message_text(text, parse_mode="HTML", reply_markup=main_menu_keyboard())
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
        text = build_today_overview(user) + "\n\nKako ti je prosao dan? Izaberi najblizu opciju:"
        await query.edit_message_text(text, parse_mode="HTML", reply_markup=mood_keyboard())
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
    app.add_handler(CommandHandler("test22", test22))
    app.add_handler(conv_handler)
    app.add_handler(CallbackQueryHandler(cb_router))
    app.add_error_handler(error_handler)
    print("[bot] Starting Telegram bot...")
    app.run_polling()

if __name__ == "__main__":
    main()
