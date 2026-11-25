"""The official line numbers and descriptions of Poreski bilans (Obrazac PB 1), display only.

The PB-1 workbook's descriptions came from an older version of the form: several were long,
some had typos, and the formula texts named the old line numbers (e.g. "Oporeziva dobit ...
do 51", "Poreska osnovica (55+61)"). The user gave the current official form (ePorezi, PP-PDP
-> PB1, lines 1-69, in Cyrillic; 2026-11-22) and asked for its texts in Latin script, shortened
where that reads better, and for the "#" column to follow its numbering.

Keyed by the Excel row (the app's row key). Each entry names the line number the workbook has
in column A, so a different template is noticed (WARNING, the entry is skipped) instead of
putting a text on the wrong row. Applied in `_read_sheet` (app/pb1_workbook.py) after the typo
corrections; the workbook and the stored snapshot are not changed.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class OfficialLine:
    row: int  # Excel row
    file_number: int | None  # line number in column A of the workbook (None: section heading)
    number: int | None  # official line number shown in "#" (None: none)
    text: str  # description shown in "Opis"


_LINES: tuple[tuple[int, int | None, int | None, str], ...] = (
    (5, None, None, "A. Dobitak i gubitak pre oporezivanja"),
    (6, None, None, "I Rezultat u Bilansu uspeha"),
    (7, 1, 1, "Dobitak poslovne godine (AOP 223 Bilansa uspeha)"),
    (8, 2, 2, "Prihod ogranka nerezidentnog pravnog lica koji se ne oporezuje po potvrđenom međunarodnom "
              "ugovoru, odnosno iz jurisdikcije sa preferencijalnim poreskim sistemom (član 40. st. 12. i 13. Zakona)"),
    (9, 3, 3, "Gubitak poslovne godine (AOP 224 Bilansa uspeha)"),
    (10, None, None, "II Dobici i gubici od prodaje imovine iz člana 27. Zakona (iskazani u Bilansu uspeha)"),
    (11, 4, 4, "Dobici od prodaje imovine"),
    (12, 5, 5, "Gubici od prodaje imovine"),
    (13, None, None, "III Usklađivanje rashoda"),
    (14, 6, 6, "Troškovi koji nisu dokumentovani"),
    (15, 7, 7, "Ispravke vrednosti pojedinačnih potraživanja od lica kome se istovremeno duguje, do iznosa "
                "obaveze prema tom licu"),
    (16, 8, 8, "Pokloni i prilozi dati političkim organizacijama"),
    (17, 9, 9, "Pokloni čiji je primalac povezano lice"),
    (18, 10, 10, "Kamate zbog neblagovremeno plaćenih poreza, doprinosa i drugih javnih dažbina"),
    (19, 11, 11, "Troškovi postupka prinudne naplate poreza i drugih dugovanja, troškovi poreskoprekršajnog i "
                 "drugih prekršajnih postupaka"),
    (20, 12, 12, "Novčane kazne, ugovorne kazne i penali"),
    (21, 13, 13, "Zatezne kamate između povezanih lica"),
    (22, 14, 14, "Troškovi koji nisu nastali u svrhu obavljanja poslovne delatnosti"),
    (23, 15, 15, "Troškovi materijala i nabavna vrednost prodate robe iznad iznosa obračunatog metodom "
                 "ponderisane prosečne cene ili FIFO metodom"),
    (24, 16, 16, "Primanja zaposlenog iz člana 9. stav 2. Zakona, obračunata a neisplaćena u poreskom periodu"),
    (25, 17, 17, "Otpremnine i novčane naknade po osnovu prestanka radnog odnosa, obračunate a neisplaćene u "
                 "poreskom periodu"),
    (26, 18, 18, "Primanja zaposlenog iz člana 9. stav 2. Zakona, obračunata u prethodnom, a isplaćena u ovom "
                 "poreskom periodu"),
    (27, 19, 19, "Otpremnine i novčane naknade po osnovu prestanka radnog odnosa, obračunate u prethodnom, a "
                 "isplaćene u ovom poreskom periodu"),
    (28, 20, 20, "Ukupan iznos amortizacije obračunat u finansijskim izveštajima"),
    (29, 21, 21, "Ukupan iznos amortizacije koji se priznaje za poreske svrhe"),
    (30, 22, 22, "Izdaci za zdravstvene, obrazovne, naučne, humanitarne, verske i sportske namene, zaštitu "
                 "životne sredine, socijalnu zaštitu i humanitarnu pomoć u vanrednoj situaciji"),
    (31, 23, 23, "Izdaci za ulaganja u oblasti kulture"),
    (32, 24, 24, "Članarine komorama, savezima i udruženjima"),
    (33, 25, 25, "Rashodi po osnovu reprezentacije"),
    (34, 26, 26, "Rashod po osnovu ispravke vrednosti pojedinačnih potraživanja ako od roka za njihovu naplatu "
                 "nije prošlo najmanje 60 dana, kao i otpis bez prethodno ispunjenih uslova iz člana 16, "
                 "odnosno člana 22a Zakona"),
    (35, 27, 27, "Rashod po osnovu ispravke vrednosti pojedinačnih potraživanja koji nije bio priznat u periodu "
                 "u kom je iskazan, a priznaje se naknadno (član 16. Zakona)"),
    (36, 28, 28, "Troškovi ogranka nerezidentnog obveznika iz člana 20. Zakona; rashod ogranka u vezi sa "
                 "prihodom koji se ne oporezuje po međunarodnom ugovoru, odnosno iz jurisdikcije sa "
                 "preferencijalnim poreskim sistemom (član 40. st. 12. i 13. Zakona)"),
    (37, 29, 29, "Porezi, doprinosi, takse i druge javne dažbine koje ne zavise od rezultata poslovanja, nisu "
                 "plaćene u poreskom periodu, a iskazane su kao rashod"),
    (38, 30, 30, "Porezi, doprinosi, takse i druge javne dažbine koje ne zavise od rezultata poslovanja, plaćene "
                 "u poreskom periodu, a iskazane kao rashod u prethodnom periodu, kada nisu bile plaćene"),
    (39, 31, 31, "Rashod banke po osnovu ispravke vrednosti potraživanja bilansne aktive i rezervisanja za "
                 "gubitke po vanbilansnim stavkama, koji se ne priznaje (član 22a Zakona)"),
    # The workbook numbers this line 31 a second time.
    (40, 31, 32, "Dugoročna rezervisanja koja se ne priznaju u poreskom periodu"),
    # Row 41 (the workbook's 32) is not a line of the current form: removed (spec.dropped_rows).
    (42, 33, 33, "Dugoročna rezervisanja u iznosu koji je iskorišćen u poreskom periodu"),
    (43, 34, 34, "Rashodi po osnovu obezvređenja imovine"),
    (44, 35, 35, "Rashodi po osnovu obezvređenja imovine koji se priznaju u periodu u kom je imovina otuđena, "
                 "upotrebljena ili oštećena usled više sile; rashodi zbog promene računovodstvene politike pri "
                 "prvoj primeni MRS, odnosno MSFI i MSFI za MSP"),
    (45, 36, 36, "Troškovi istraživanja i razvoja koji se priznaju u dvostrukom iznosu (član 22g Zakona)"),
    (46, None, None, "IV Usklađivanje prihoda"),
    (47, 37, 37, "Porez na dobit koji je u drugoj državi platila nerezidentna filijala rezidentnog matičnog "
                 "pravnog lica"),
    (48, 38, 38, "Porez po odbitku na dividende koji je u drugoj državi platila nerezidentna filijala "
                 "rezidentnog matičnog pravnog lica"),
    (49, 39, 39, "Porez po odbitku na kamate, autorske naknade, zakupnine i dividende koje ne ispunjavaju "
                 "uslove za poreski kredit (član 52. Zakona), kao i na usluge, plaćen u drugoj državi"),
    (50, 40, 40, "Porez na kapitalni dobitak plaćen u drugoj državi"),
    (51, 41, 41, "Ispravke vrednosti pojedinačnih potraživanja priznate na teret rashoda, za koje u periodu "
                 "otpisa nisu ispunjeni uslovi iz člana 16. Zakona"),
    (52, 42, 42, "Sva otpisana, ispravljena i druga potraživanja priznata kao rashod, koja se u poreskom periodu "
                 "uključuju u oporezive prihode, a nisu tako iskazana u poslovnim knjigama; prihodi zbog promene "
                 "računovodstvene politike pri prvoj primeni MRS, odnosno MSFI i MSFI za MSP"),
    (53, 43, 43, "Iznos koji se po osnovu smanjenja procenta korišćenja stalnih sredstava za istraživanje i "
                 "razvoj uključuje u poresku osnovicu"),
    (54, 44, 44, "Iznos koji se uključuje u poresku osnovicu u periodu u kom je prijava pronalaska odbačena"),
    (55, 45, 45, "Prihodi po osnovu otpisanih, ispravljenih i drugih potraživanja koja nisu bila priznata kao "
                 "rashod, a ne uključuju se u oporezive prihode"),
    (56, 46, 46, "Prihod po osnovu dividendi i udela u dobiti od drugog rezidentnog obveznika"),
    (57, 47, 47, "Prihodi od kamata na dužničke hartije od vrednosti čiji je izdavalac Republika, autonomna "
                 "pokrajina, jedinica lokalne samouprave ili NBS; prihod investicionog fonda od otuđenja imovine "
                 "iz člana 27. stav 1. Zakona"),
    (58, 48, 48, "Prihodi od neiskorišćenih dugoročnih rezervisanja koja nisu bila priznata kao rashod u periodu "
                 "u kom su izvršena; prihodi od sticanja nenovčane imovine u realizaciji ugovora o koncesiji"),
    (59, 49, 49, "Prihodi u vezi sa rashodima koji nisu bili priznati; prihodi od smanjenja obaveza prema "
                 "korisnicima javnih sredstava, bankama u stečaju i privrednim komorama, obuhvaćenih UPPR-om"),
    (60, 50, 50, "Iznos kvalifikovanog prihoda koji se ne uključuje u poresku osnovicu (član 25b Zakona)"),
    (61, None, None, "V Rashodi i prihodi po osnovu transfernih cena (osim kamata na zajmove, odnosno kredite)"),
    (62, 51, 51, "Obračunati troškovi po osnovu transfernih cena"),
    (63, 52, 52, "Obračunati troškovi po osnovu transfernih cena za koje se podnosi izveštaj u skraćenom obliku"),
    (64, 53, 53, "Obračunati prihodi po osnovu transfernih cena"),
    (65, 54, 54, "Obračunati prihodi po osnovu transfernih cena za koje se podnosi izveštaj u skraćenom obliku"),
    (66, None, None, "VI Rashodi i prihodi po osnovu kamata na zajmove, odnosno kredite između povezanih lica"),
    (67, 55, 55, "Obračunati rashodi po osnovu kamata (\"na dohvat ruke\") na zajmove, odnosno kredite dobijene "
                 "od povezanih lica"),
    (68, 56, 56, "Obračunati prihodi po osnovu kamata (\"na dohvat ruke\") na zajmove, odnosno kredite odobrene "
                 "povezanim licima"),
    (69, None, None, "VII Korekcija rashoda i prihoda po osnovu transfernih cena, uključujući i kamate na zajmove, "
                     "odnosno kredite između povezanih lica"),
    (70, 57, 57, "Zbir konačnih korekcija (rashoda i prihoda) po osnovu transakcija sa svim povezanim licima, "
                 "utvrđen u dokumentaciji o transfernim cenama"),
    (71, None, None, "VIII Korekcija rashoda po osnovu sprečavanja utanjene kapitalizacije"),
    (72, 58, 58, "Kamata i pripadajući troškovi na zajam, odnosno kredit iznad četvorostruke (desetostruke) "
                 "vrednosti sopstvenog kapitala (red. br. 13 Obrasca OK)"),
    (73, None, None, "IX Dobit usklađena na način propisan Zakonom"),
    (74, 59, 59, "Dobit (1-2-4+5 do 17-18-19+20-21+22 do 26-27+28+29-30+31+32-33+34-35-36+37 do 44-45 do 50"
                 "+57+58) > 0 (ili negativan iznos sa red. br. 60)"),
    (75, 60, 60, "Gubitak (3+2+4-5 do 17+18+19-20+21-22 do 26+27-28-29+30-31-32+33-34+35+36-37 do 44+45 do 50"
                 "-57-58) > 0 (ili negativan iznos sa red. br. 59)"),
    (76, 61, 61, "Iznos gubitka iz poreskog bilansa iz prethodnih godina, do visine dobiti"),
    (77, 62, 62, "Ostatak dobiti (59-61) > 0"),
    (78, None, None, "B. Kapitalni dobici i gubici"),
    (79, 63, 63, "Ukupni kapitalni dobici tekuće godine obračunati u skladu sa Zakonom"),
    (80, 64, 64, "Ukupni kapitalni gubici tekuće godine obračunati u skladu sa Zakonom"),
    (81, 65, 65, "Kapitalni dobici (63-64) > 0"),
    (82, 66, 66, "Kapitalni gubici (64-63) > 0"),
    (83, 67, 67, "Preneti kapitalni gubici iz ranijih godina do visine iznosa pod red. br. 65"),
    (84, 68, 68, "Ostatak kapitalnog dobitka (65-67) > 0"),
    # Closing rows: the heading stays "Poreska osnovica" (user, 2026-11-17: no "V."); line 69
    # has no "#" there (its column A is not part of the form).
    (86, None, None, "Poreska osnovica (62+68) > 0"),
)

OFFICIAL_LINES: dict[str, tuple[OfficialLine, ...]] = {
    "poreski-bilans": tuple(OfficialLine(*line) for line in _LINES),
}
