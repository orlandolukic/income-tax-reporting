"""Podvrsta options of each Vrsta of a financial order (Finansije › Finansijski nalozi), as TiM ERP loads them
when Vrsta changes. Read once from the program (all 26 Vrste, 2026-10-10); they don't change, so the program is
not asked for them any more.
"""

PODVRSTE: dict[str, list[str]] = {
    'Izvodi': ['Domaća valuta', 'Devizna valuta'],
    'Blagajna': ['Domaća valuta', 'Devizna valuta', 'Menjačnica'],
    'Zarade': ['IZ radnog odnosa', 'VAN radnog odnosa', 'Osnivači koji nisu u radnom odnosu u svom preduzeću'],
    'Veleprodaja - ulazi': ['Ulazni račun', 'Interni ulaz/korekcija', 'Interni prenos', 'Devizni ulazni račun', 'Komision', 'Interni prenos iz carinskog magacina'],
    'Veleprodaja - izlazi': ['Izlazni račun', 'Interni izlaz/korekcija', 'Interni prenos', 'Interni otpis', 'Devizni izlazni račun', 'Interni prenos iz carinskog magacina'],
    'Veleprodaja - nivelacije': ['Nema'],
    'Proizvodnja - ulazi': ['Ulazni račun', 'Interni ulaz/korekcija', 'Interni prenos', 'Interni prenos iz carinskog magacina', 'Devizni ulazni račun'],
    'Proizvodnja - izlazi': ['Izlazni račun', 'Interni izlaz/korekcija', 'Interni prenos', 'Interni otpis', 'Devizni izlazni račun', 'Interni prenos iz carinskog magacina'],
    'Maloprodaja - ulazi': ['Ulazni račun', 'Interni ulaz/korekcija', 'Interni prenos', 'Devizni ulazni račun', 'Komision'],
    'Maloprodaja - izlazi': ['Pazar / Izlazni račun', 'Interni prenos'],
    'Maloprodaja - nivelacije': ['Nema'],
    'Troškovi': ['Domaći trošak', 'Devizni trošak'],
    'Avansni računi dobavljača': ['Nema'],
    'Avansni računi kupaca': ['Nema'],
    'Osnovna sredstva': ['Nema'],
    'Kursne razlike': ['Nema'],
    'Devizni izvodi': ['Nema'],
    'PDV Obračun': ['Nema'],
    'Odobrenja/zaduženja izlaz': ['Odobrenje/zaduženje - domaće', 'Odobrenje/zaduženje - devizno'],
    'Odobrenja/zaduženja ulaz': ['Odobrenje/zaduženje - domaće', 'Odobrenje/zaduženje - devizno'],
    'Razgraničeni PDV': ['Domaća'],
    'Službeni putevi': ['Nema'],
    'Uplate kredita': ['Nema'],
    'Početno stanje': ['Nema'],
    'Izlazni računi - direktan unos u KIR': ['Domaći', 'Devizni'],
    'Ostala knjiženja': ['Nema'],
}
