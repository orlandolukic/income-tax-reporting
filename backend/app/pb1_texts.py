"""Typo corrections for the descriptive texts of the PB-1 form (display only).

The PB-1 workbook is hand-made and is never written, so its texts are corrected when they
are read: first a general cleanup (spaces, the conjunction "I" typed in upper case), then
the corrections below, keyed by the cleaned original text. They apply wherever the text
appears (any tab, any column). The spelling without diacritics used throughout the form
(Troskovi, placanja, ...) is kept; only real typos are corrected.
"""

import re

# Cleaned original text -> corrected text.
CORRECTIONS: dict[str, str] = {
    # Headers and section headings
    "Komentar stopa konto": "Komentar, stopa, konto",
    "A Poslovna dobit i gubitak": "A. Poslovna dobit i gubitak",
    "B Poreska osnovica": "Poreska osnovica",  # heading of the closing rows; no "V." (it doesn't fit the numbering, user 2026-11-17)
    "Porez 15%": "Porez (15%)",  # closing row (user, 2026-11-25)
    "V Rashodi i prihodi po osnovu transfernih cena (osim kamata na zajmove odnosnoi kredite)":
        "V Rashodi i prihodi po osnovu transfernih cena (osim kamata na zajmove odnosno kredite)",
    "VI Rashodi i prihodi po osnovu kamata na zajmoe odnosno kredite izmedju povezanih lica":
        "VI Rashodi i prihodi po osnovu kamata na zajmove odnosno kredite izmedju povezanih lica",
    "VIII Korekcija rashoda po osnovu precavanja utanjene kapitalizacije":
        "VIII Korekcija rashoda po osnovu sprecavanja utanjene kapitalizacije",
    # Poreski bilans, descriptions (column B)
    "AOP 223 Bilans uspwha dobit poslovne godine": "AOP 223 Bilans uspeha dobit poslovne godine",
    "Dobitci od prodaje imovine": "Dobici od prodaje imovine",
    "Gubitci od prodaje imovine": "Gubici od prodaje imovine",
    "Poklon i drugi prilozi dati politickim organizacijama": "Pokloni i drugi prilozi dati politickim organizacijama",
    "Kamata zbog neblagovremenog placanja poreza doprinosa i drugih javnih prihoda":
        "Kamata zbog neblagovremenog placanja poreza, doprinosa i drugih javnih prihoda",
    "Primanja zaposlenih iz člana 9. stav 2. Zakona, obračunata u predhodno obračunskom periodu a isplaćene "
    "u poreskom periodu za koji se podnosi Bilansa neisplaćena u poreskom periodu":
        "Primanja zaposlenih iz člana 9. stav 2. Zakona, obračunata u prethodnom obračunskom periodu, a isplaćena "
        "u poreskom periodu za koji se podnosi bilans",
    "Otpremnine i novčane naknade po osnovu pretanka radnog odnosa koji su obračunati u predhodnom a isplaćene "
    "u poreskom periodu za koji se podnosi bilans":
        "Otpremnine i novčane naknade po osnovu prestanka radnog odnosa koje su obračunate u prethodnom, a isplaćene "
        "u poreskom periodu za koji se podnosi bilans",
    "Izdaci za zdravstvene, obrazovnenaucne, humanitarne, verske, zastitu covekove sredine i sportske namene":
        "Izdaci za zdravstvene, obrazovne, naucne, humanitarne, verske, zastitu covekove sredine i sportske namene",
    "Ispravka vrednosti pojedinacnih potrazivanja ako od roka za njihovu naplatu nije proslo najmanje 60 dana, "
    "kao i otpis pojedinih potrazivanja koja predhodno nisu bila ukljucena u prihod, nisu otpisana kao "
    "nenaplativa i za koja nije pruzen dokaz o neuspeloj naplati":
        "Ispravka vrednosti pojedinacnih potrazivanja ako od roka za njihovu naplatu nije proslo najmanje 60 dana, "
        "kao i otpis pojedinih potrazivanja koja prethodno nisu bila ukljucena u prihod, nisu otpisana kao "
        "nenaplativa i za koja nije pruzen dokaz o neuspeloj naplati",
    "Rashodi po osnovu ispravke vrednosti pojedinih potraživanja koji nije bio priznat u poreskom periodu u kom "
    "je iskazan ali se priznaje naknadno u skladu sa članom 16. Zakona":
        "Rashodi po osnovu ispravke vrednosti pojedinih potraživanja koji nisu bili priznati u poreskom periodu "
        "u kom su iskazani, ali se priznaju naknadno u skladu sa članom 16. Zakona",
    "Troskovi koje ogranak nerezidentnog obveznika iskazuje u skladu sa članom 20. Zakona rashod ogranka "
    "nerezidentnog pravnog lica u vezi sa prihodom koji se ne oporezuje shodno potvrdjenom medjunarodnom ugovoru "
    "Rashod ogranka nerezidentnog pravnog lica iz jurizdiukcije sa prefencijalnim poreskim sistemom iz člana 40. "
    "st.12 i 13. Zakona":
        "Troskovi koje ogranak nerezidentnog obveznika iskazuje u skladu sa članom 20. Zakona; rashod ogranka "
        "nerezidentnog pravnog lica u vezi sa prihodom koji se ne oporezuje shodno potvrdjenom medjunarodnom "
        "ugovoru; rashod ogranka nerezidentnog pravnog lica iz jurisdikcije sa preferencijalnim poreskim sistemom "
        "iz člana 40. st. 12 i 13. Zakona",
    "Porezi, doprinosi, takse i druge javne dazbine koje ne zavise od rezultata poslovanja, a koje nisu placene "
    "u poreskomk periodu a po osnovu kojih je u poslovnim knjigama obveznik iskazao rashod":
        "Porezi, doprinosi, takse i druge javne dazbine koje ne zavise od rezultata poslovanja, a koje nisu placene "
        "u poreskom periodu, a po osnovu kojih je u poslovnim knjigama obveznik iskazao rashod",
    "Porezi, doprinosi, takse i druge javne dazbine koje ne zavise od rezultata poslovanja, placene u porskom "
    "periodu a koje nisu bile placene u predhodnoim poreskom periodu u kome je po tom osnovu u poslovnim knjigama "
    "obveznik bio iskazao rashos":
        "Porezi, doprinosi, takse i druge javne dazbine koje ne zavise od rezultata poslovanja, placene u poreskom "
        "periodu, a koje nisu bile placene u prethodnom poreskom periodu u kome je po tom osnovu u poslovnim "
        "knjigama obveznik bio iskazao rashod",
    "Rashod banke po osnovu ispravke vrednosti potraživanja bilansne aktive i rezervisanja za gubitke po "
    "vanbilansnim stavkama u iznosu kjoji se ne priznaje u skladu sa članom 22a Zakona":
        "Rashod banke po osnovu ispravke vrednosti potraživanja bilansne aktive i rezervisanja za gubitke po "
        "vanbilansnim stavkama u iznosu koji se ne priznaje u skladu sa članom 22a Zakona",
    "Troskovi istraživanja i razvoja koji se proznaju u dvostrukom iznosu u skladu sa članom 22g Zakona":
        "Troskovi istraživanja i razvoja koji se priznaju u dvostrukom iznosu u skladu sa članom 22g Zakona",
    "Porez po odbitku na dividende koji je u drugoj državi platila nerezidenntna filijala matičnog pravnog lica":
        "Porez po odbitku na dividende koji je u drugoj državi platila nerezidentna filijala matičnog pravnog lica",
    "Porez po odbitku na kamate i autorske naknade naknade po osnovu zakupa nepokretnosti i pokretnih stvari i "
    "dividende koje ne ispunjavaju uslove za poreski kredit po clanu 52. Zakona placen u drugoj zemlji":
        "Porez po odbitku na kamate i autorske naknade, naknade po osnovu zakupa nepokretnosti i pokretnih stvari i "
        "dividende koje ne ispunjavaju uslove za poreski kredit po clanu 52. Zakona, placen u drugoj zemlji",
    "Porez na kapiotalni dobitak placen u drugoj državi": "Porez na kapitalni dobitak placen u drugoj državi",
    "Ispravka vrdnosti pojedinaćčnih potraživanja koje su bile priznate na teret rashoda a za koje u poreskom "
    "periodu u kome se vrši otpis nisu kumulativno ispunjeni uslovi iz člana 16 Zakona":
        "Ispravka vrednosti pojedinačnih potraživanja koje su bile priznate na teret rashoda, a za koje u poreskom "
        "periodu u kome se vrši otpis nisu kumulativno ispunjeni uslovi iz člana 16. Zakona",
    "Sva otpisana ispravljena i druga potraživanja koja su bila priznata kao rashod a koja se u poreskom periodu "
    "uključuju u oporezive prihode koji nisu kao takvi iskazani u poslovnim knjigama obveznika rashodi nastali po "
    "osnovu efekta promene računovodstvene politike usled prve primene MRS odnosno MSFI i MSFI sa MSP":
        "Sva otpisana ispravljena i druga potraživanja koja su bila priznata kao rashod, a koja se u poreskom periodu "
        "uključuju u oporezive prihode koji nisu kao takvi iskazani u poslovnim knjigama obveznika; rashodi nastali "
        "po osnovu efekta promene računovodstvene politike usled prve primene MRS odnosno MSFI i MSFI za MSP",
    "Iznos koji se po osnovu smanjenja procenta korisćenja stalnih sredstava za svrhe istraživanja i razvoja "
    "uključuju u poresku osnoviicu":
        "Iznos koji se po osnovu smanjenja procenta korišćenja stalnih sredstava za svrhe istraživanja i razvoja "
        "uključuje u poresku osnovicu",
    "Iznos koji se uključuje u poresku osnovicu u poreskom periodu um kojem je prijava u vezi sa pronalaskom "
    "odbačena od strane nadležnog organa":
        "Iznos koji se uključuje u poresku osnovicu u poreskom periodu u kojem je prijava u vezi sa pronalaskom "
        "odbačena od strane nadležnog organa",
    "Prihodi po osnovu dividendi i udela u dobiti od drugog rezistentnog obveznika":
        "Prihodi po osnovu dividendi i udela u dobiti od drugog rezidentnog obveznika",
    "Prihodi od kamata po osnovu duzničkih hartija od vrednosti čiji je izdavalac Republika autonomn pokrajina, "
    "jedinica lokalne samouprave ili NBS prihod investicionog fonda ostvaren po osnovu otudjenja imovine iz "
    "člana 27. stav 12. Zakona":
        "Prihodi od kamata po osnovu dužničkih hartija od vrednosti čiji je izdavalac Republika, autonomna "
        "pokrajina, jedinica lokalne samouprave ili NBS; prihod investicionog fonda ostvaren po osnovu otudjenja "
        "imovine iz člana 27. stav 12. Zakona",
    "Prihodi po osnovu neiskorišćenih dugoročnih rezervisanja koja nisu bila priznata kao rashod u poreskom "
    "periodu u kome su izvršena , prihodi nastali po osnovu sticanja nenovčane imovine u postupku realizacije "
    "ugovora o koncesiji":
        "Prihodi po osnovu neiskorišćenih dugoročnih rezervisanja koja nisu bila priznata kao rashod u poreskom "
        "periodu u kome su izvršena; prihodi nastali po osnovu sticanja nenovčane imovine u postupku realizacije "
        "ugovora o koncesiji",
    "Prihodi nastali u vezi sa rahodima koji nisu bili priznati predhodni nastali po osnovu smanjanja obaveza "
    "prema korisnicima javnih sredstava, bankama u stečaju i privrednim komorama koje su obugvaćene UPPE-om":
        "Prihodi nastali u vezi sa rashodima koji nisu bili priznati prethodno; prihodi nastali po osnovu smanjenja "
        "obaveza prema korisnicima javnih sredstava, bankama u stečaju i privrednim komorama koje su obuhvaćene "
        "UPPR-om",
    "Iznos kvalifikovanog prihoda koji se u skladu sa članom 25b Zakona ne uključije u poresku osnovicu":
        "Iznos kvalifikovanog prihoda koji se u skladu sa članom 25b Zakona ne uključuje u poresku osnovicu",
    "Obracunati prihod po osnovu kamat (na dohvat ruke) na zajmove onosno kredite dobijene od povezanih lica":
        "Obracunati prihod po osnovu kamata (na dohvat ruke) na zajmove odnosno kredite dobijene od povezanih lica",
    "Kamata i pripadajuci troskovi na zajam odnosno kredit iznad nivoa cetvorostruke (desetostruke) vrednosto "
    "obveznikovog sopstveog kapital (redni broj 13. Obrasca OK)":
        "Kamata i pripadajuci troskovi na zajam odnosno kredit iznad nivoa cetvorostruke (desetostruke) vrednosti "
        "obveznikovog sopstvenog kapitala (redni broj 13. Obrasca OK)",
    "Gubitak ( 3+4-5 do 16+17-18+19-20 do 27 +28-29 do 31 +32-33 +34-35 do 38 +39 do 43 -50-51)>0 "
    "(ili negativan iznos sa rednog broja 52)":
        "Gubitak (3+4-5 do 16+17-18+19-20 do 27 +28-29 do 31 +32-33 +34-35 do 38 +39 do 43 -50-51) > 0 "
        "(ili negativan iznos sa rednog broja 52)",
    "Iznos gubitka iz poreskog bilansa iz predhodnih godina, do visine oporezive dobiti":
        "Iznos gubitka iz poreskog bilansa iz prethodnih godina, do visine oporezive dobiti",
    "Ukupni kaptalni dobici tekuce godine obracunati u skladu sa Zakonom":
        "Ukupni kapitalni dobici tekuce godine obracunati u skladu sa Zakonom",
    "Ukupnii kapitalni gubitci": "Ukupni kapitalni gubici",
    "Kaptalni dobici (56-57)> 0": "Kapitalni dobici (56-57) > 0",
    "Kaptalni gubici (57-56) >0": "Kapitalni gubici (57-56) > 0",
    "Preneti kapitalni gubici iz ranjih godina do visine iznosa pod rednim brojem 58":
        "Preneti kapitalni gubici iz ranijih godina do visine iznosa pod rednim brojem 58",
    "Ostatak kapitalnog dobitka (58-60)> 0": "Ostatak kapitalnog dobitka (58-60) > 0",
    # Poreski bilans, comments (column F)
    "razlika Otpisano potrazivanje minus Obaveza": "Razlika: otpisano potrazivanje minus obaveza",
    "Placeno r.b.16 iz predhodne godine": "Placeno r.b. 16 iz prethodne godine",
    "komunalna taksa gradjevinsko zemlj. i sl": "Komunalna taksa, gradjevinsko zemljiste i sl.",
    "Placeni iznos sa r.b26. iz predhodne godine": "Placeni iznos sa r.b. 26 iz prethodne godine",
    "Placeno r.b.30 iz predhodne godine": "Placeno r.b. 30 iz prethodne godine",
    "Izvrsena prodaja za r.b.32 iz predhodne godine": "Izvrsena prodaja za r.b. 32 iz prethodne godine",
    # Uporedo and Preliminarni rezultat
    "Ukupan Rashod": "Ukupan rashod",
    "Dobit perioda Bruto dobit": "Dobit perioda (bruto dobit)",
    "Uvecanje porske osnovice": "Uvecanje poreske osnovice",
    "Umanjenje porske osnovice": "Umanjenje poreske osnovice",
    "Poreska osnovica (3+4+6+7)>0": "Poreska osnovica (3+4+6+7) > 0",
    "Konacni porez na dobt (9-10)": "Konacni porez na dobit (9-10)",
    "Konacni porez na dobt za 2025 (9-10)": "Konacni porez na dobit za 2025 (9-10)",
    "Uplacenje akontacije u tekucoj godini": "Uplacene akontacije u tekucoj godini",
    "Uplacenje akontacije tokom 2025.god": "Uplacene akontacije tokom 2025. godine",
    "Za Uplatu porez na dobit po Godisnjem obracunu (11-12)>0": "Za uplatu porez na dobit po godisnjem obracunu (11-12) > 0",
    "Za Uplatu porez na dobit po Godisnjem obracunu za 2024 (11-12)>0":
        "Za uplatu porez na dobit po godisnjem obracunu za 2024 (11-12) > 0",
    "Pretplata poreza na dobit (11-12)<0": "Pretplata poreza na dobit (11-12) < 0",
    "Preliminarni rezultati 2025.god": "Preliminarni rezultati 2025. godine",
    "Mesecna akontacija poreza na dobit u 2025.godini (9:12)": "Mesecna akontacija poreza na dobit u 2025. godini (9:12)",
    "Ukupno Uvecanje Poreske osnovice (1 do 8)": "Ukupno uvecanje poreske osnovice (1 do 8)",
    "Ukupno Umanjenje Poreske osnovice (1 do 6)": "Ukupno umanjenje poreske osnovice (1 do 6)",
    "po osnovu Investicionih ulaganja": "Po osnovu investicionih ulaganja",
    "POSLOVNI dobitak gubitak": "Poslovni dobitak / gubitak",
    "Finansijski dobitak gubitak": "Finansijski dobitak / gubitak",
    "Bruto dobitak gubitak": "Bruto dobitak / gubitak",
    "Porezi i doprinos": "Porezi i doprinosi",
}

# The conjunction "i" typed as "I" inside a sentence (not a Roman numeral at the start).
_UPPER_CONJUNCTION = re.compile(r"(?<=\S) I (?=\S)")


def clean_text(text: str) -> str:
    """General cleanup: single spaces, no spaces at the ends, conjunction "I" -> "i"."""
    return _UPPER_CONJUNCTION.sub(" i ", " ".join(text.split()))


def correct_text(text: str) -> str:
    """The corrected display text of a descriptive PB-1 text."""
    cleaned = clean_text(text)
    return CORRECTIONS.get(cleaned, cleaned)
