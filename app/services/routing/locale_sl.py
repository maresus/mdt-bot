BOOKING_KEYWORDS = [
    "naroči",
    "naročilo",
    "naroci",
    "narocilo",
    "termin",
    "rezerv",
    "naročil",
    "naročila",
    "narocil",
    "narocila",
    "rad bi",
    "rada bi",
    "bi rad",
    "bi rada",
    "želel",
    "želela",
    "zelim",
    "želim",
    "hočem",
    "hocem",
]

PRICE_WORDS = ["cena", "cene", "cenik", "koliko", "stane"]

SYMPTOM_MARKERS = [
    "boli",
    "boleč",
    "bolec",
    "bolečin",
    "bolecin",
    "težav",
    "tezav",
    "srbi",
    "izpuščaj",
    "izpuscaj",
    "otekl",
    "bula",
    "bulo",
    "bulica",
    "slabo vidim",
    "imam",
    "me ",
]

QUESTION_MARKERS = ["?", "kaj", "kako", "kateri", "katere", "koliko", "kdaj", "kje", "ali "]

SYMPTOM_PATTERNS = [
    "boli me",
    "boli mi",
    "imam težave",
    "imam tezave",
    "me boli",
    "mi boli",
    "bolečine v",
    "bolecine v",
    "srbečica",
    "srbecica",
    "otekl",
    "izpuščaj",
    "srbi",
    "srbi me",
    "srbeče",
    "srbeco",
    "znamenje",
    "bula",
    "bulo mam",
    "mam bulo",
    "kožno znamenje",
    "kozni madez",
    "kožni madež",
    "glavobol",
    "migrena",
    "omotica",
]

SYMPTOM_WORDS = [
    "boli",
    "bolec",
    "boleč",
    "bolečin",
    "težav",
    "simptom",
    "srbi",
    "srbe",
    "srbeč",
    "srbec",
    "izpuščaj",
    "izpuscaj",
    "bula",
    "bulo",
    "bulica",
    "znamenje",
    "madež",
    "madez",
    "koža",
    "koza",
    "glavobol",
    "migrena",
    "omotica",
]

BOOKING_INFO_PHRASES = [
    "kako se naročim",
    "kako se narocim",
    "kako poteka naročanje",
    "kako poteka narocanje",
    "kako rezerviram",
    "kako rezervirati",
    "kako do termina",
    "kako pridem do termina",
]

AVAILABILITY_PHRASES = [
    "proste termine",
    "prosti termini",
    "razpoložljivi termini",
    "razpolozljivi termini",
]

BOOKING_KEYWORDS_EXTENDED = [
    "naroči",
    "naročilo",
    "naroci",
    "narocilo",
    "termin",
    "rezerv",
    "želim",
    "zelim",
    "potrebujem",
    "rad bi",
    "rada bi",
    "bi rad",
    "bi rada",
    "naročil",
    "naročila",
    "narocil",
    "narocila",
    "hočem",
    "hocem",
    "želel",
    "želela",
    "vrzi",
    "vrži",
    "naroči me",
    "naroci me",
    "book",
]

HOURS_WORDS = [
    "delovni čas",
    "delovni cas",
    "delovn cas",
    "delovn",
    "odprto",
    "odprti",
    "kdaj ste odprti",
    "do kdaj",
    "od kdaj",
]

AVAILABILITY_WORDS = ["prost", "razpoložljiv", "razpolozljiv", "kdaj", "termin"]

SERVICE_INFO_TOKENS = ["cena", "cene", "koliko", "stane", "opis", "kaj", "ponudba", "storitve", "kakšne", "kaksne"]

SERVICE_LIST_WORDS = ["storitve", "pregled", "ponudba", "kaj ponujate"]

TEAM_WORDS = ["šef", "sef", "vodja", "vodstvo", "direktor", "kdo vodi", "kdo je glavni", "ekipa", "zdravniki", "kdo dela pri vas"]

CONTACT_WORDS = ["kontakt", "telefon", "email", "naslov", "lokacija", "nahaja", "kje ste", "kje se", "naslovom", "pridi", "pridem", "parkir", "parking", "parkiri"]

THANKS_WORDS = ["hvala", "najlepša hvala", "hvala lepa", "thanks", "thx"]

GREETING_WORDS = ["pozdravljeni", "živjo", "zivjo", "dober dan", "zdravo", "zdravjo", "zdwavo", "hej", "halo", "bok"]

FULL_NAME_BLOCKED_TOKENS = [
    "koliko",
    "stane",
    "cena",
    "cenik",
    "parking",
    "park",
    "kako",
    "kje",
    "kontakt",
    "ura",
    "termin",
    "pregled",
    "storitev",
    "delate",
    "sobota",
    "nedelja",
]

FULL_NAME_BLOCKED_SINGLE = [
    "koleno",
    "hrbet",
    "glava",
    "izpuščaj",
    "izpuscaj",
    "znamenje",
    "koža",
    "koza",
    "bolečina",
    "bolečine",
    "bolecina",
    "bolecine",
    "srbi",
    "srbe",
    "srbeč",
    "srbec",
    "dermatološki",
    "ortopedski",
    "okulistični",
    "okulisticni",
    "laser",
    "laserski",
    "estetski",
    "kozmetični",
    "kozmeticni",
    "pregled",
    "termin",
]

RELATIVE_DATES = {
    "danes": 0,
    "jutri": 1,
    "pojutrišnjem": 2,
}

SERVICE_KEYWORDS = {
    "ortoped": ["ortoped", "ortopedski", "ortopedija"],
    "dermatolog": ["dermatolog", "dermatološki", "dermatologija"],
    "okulist": ["okulist", "okulistični", "oftalmolog", "očesni"],
    "kozmetika": ["kozmetik", "kozmetični"],
    "estetski_poseg": ["estetski", "botox", "filer"],
    "laserski_poseg": ["laser", "laserski"],
}

BOOKING_RELEVANT_KEYS = {
    "dermatolog",
    "ortoped",
    "okulist",
    "laserski_poseg",
    "estetski_poseg",
    "kozmetika",
    "storitve",
    "prosti_termini",
}

CRITICAL_INFO_KEYS = {
    "delovni_cas",
    "kontakt",
    "cene",
    "storitve",
    "prosti_termini",
    "dermatolog",
    "ortoped",
    "okulist",
    "laserski_poseg",
    "estetski_poseg",
    "kozmetika",
}

SKIP_SERVICE_KEYWORDS = {"oči", "oci"}

CONTACT_ROUTE_WORDS = ["pridem", "pridemo", "pot"]
