"""TiM ERP main menu, as scanned from the live site on 2026-10-06 (the menu scan itself was removed).

Each item is opened by the site's own `mnClk(group, item, dialog)` (see CLAUDE.md): it posts the
choice to the server, and `dialog == 1` opens the page in an iframe. "Ostalo" also has two help links
(`mnClk2`, they open a new tab) that are left out here.
"""
from dataclasses import dataclass


@dataclass(frozen=True)
class MenuItem:
    group: str  # dropdown name, e.g. "Registri"
    name: str  # item text, e.g. "Komitenti"
    group_id: int  # mnClk arguments
    item_id: int
    dialog: int

    @property
    def path(self) -> str:
        return f"{self.group} > {self.name}"

    @property
    def js(self) -> str:
        return f"mnClk({self.group_id},{self.item_id},{self.dialog})"


MENU: list[MenuItem] = [
    # Registri
    MenuItem('Registri', 'Podaci o firmi', 1, 1, 0),
    MenuItem('Registri', 'Magacini', 1, 2, 0),
    MenuItem('Registri', 'Komitenti', 1, 3, 0),
    MenuItem('Registri', 'Kontakti', 1, 4, 0),
    MenuItem('Registri', 'Robe i usluge', 1, 5, 0),
    MenuItem('Registri', 'Nalepnice', 1, 6, 0),
    MenuItem('Registri', 'Grupe roba', 1, 7, 0),
    MenuItem('Registri', 'Grupe komitenata', 1, 8, 0),
    MenuItem('Registri', 'Proizvođači', 1, 9, 0),
    MenuItem('Registri', 'Organizacione jedinice', 1, 10, 0),
    MenuItem('Registri', 'Mesta prihoda i troškova', 1, 11, 0),
    MenuItem('Registri', 'Kursevi', 1, 12, 0),
    MenuItem('Registri', 'Tekstovi', 1, 13, 0),
    MenuItem('Registri', 'Radnici', 1, 14, 0),
    MenuItem('Registri', 'Osnovna sredstva', 1, 15, 0),
    MenuItem('Registri', 'Grupe osnovnih sredstava', 1, 16, 0),
    MenuItem('Registri', 'Liste roba', 1, 17, 0),
    # Finansije
    MenuItem('Finansije', 'Virmani', 2, 1, 0),
    MenuItem('Finansije', 'Kontni plan', 2, 3, 0),
    MenuItem('Finansije', 'Šeme kontiranja', 2, 4, 0),
    MenuItem('Finansije', 'Finansijski nalozi', 2, 6, 0),
    MenuItem('Finansije', 'Blagajna', 2, 7, 0),
    MenuItem('Finansije', 'Izvodi', 2, 9, 0),
    MenuItem('Finansije', 'Ispravka nabavnih cena', 2, 11, 0),
    MenuItem('Finansije', 'Provera knjiženja roba i usluga', 2, 12, 0),
    MenuItem('Finansije', 'Obračuni zarada', 2, 14, 0),
    MenuItem('Finansije', 'Obračuni knjigovodstvene amortizacije', 2, 16, 0),
    MenuItem('Finansije', 'Obračuni poreske amortizacije', 2, 17, 0),
    MenuItem('Finansije', 'Službeni putevi', 2, 19, 0),
    MenuItem('Finansije', 'Izvod otvorenih stavki', 2, 21, 0),
    MenuItem('Finansije', 'Predlog za kompenzacije', 2, 22, 0),
    MenuItem('Finansije', 'Obračun po deviznoj klauzuli', 2, 23, 0),
    MenuItem('Finansije', 'Pregled dugovanja', 2, 24, 0),
    MenuItem('Finansije', 'Bilans stanja, uspeha, statistički izveštaj', 2, 26, 0),
    MenuItem('Finansije', 'Izveštaji', 2, 28, 0),
    # KPR / KIR (!)
    MenuItem('KPR / KIR (!)', 'PDV Obračuni', 3, 1, 0),
    MenuItem('KPR / KIR (!)', 'KPR', 3, 3, 0),
    MenuItem('KPR / KIR (!)', 'Troškovi', 3, 4, 0),
    MenuItem('KPR / KIR (!)', 'Ulazni Računi (VP, MP, Proizvodnja)', 3, 5, 0),
    MenuItem('KPR / KIR (!)', 'Avansi dobavljača', 3, 6, 0),
    MenuItem('KPR / KIR (!)', 'Razgraničeni ulazni PDV', 3, 7, 0),
    MenuItem('KPR / KIR (!)', 'Odobrenja, zaduženja dobavljača', 3, 8, 0),
    MenuItem('KPR / KIR (!)', 'QR kodovi fisk. računa - Primljeni', 3, 9, 0),
    MenuItem('KPR / KIR (!)', 'E-Fakture - Primljene (!)', 3, 10, 0),
    MenuItem('KPR / KIR (!)', 'KIR', 3, 12, 0),
    MenuItem('KPR / KIR (!)', 'Odobrenja, zaduženja kupcima', 3, 13, 0),
    MenuItem('KPR / KIR (!)', 'Izlazni računi (VP, MP, Proizvodnja)', 3, 14, 0),
    MenuItem('KPR / KIR (!)', 'Izlazni računi - direktan unos u KIR', 3, 15, 0),
    MenuItem('KPR / KIR (!)', 'Avansi kupaca', 3, 16, 0),
    MenuItem('KPR / KIR (!)', 'Razgraničeni izlazni PDV', 3, 17, 0),
    MenuItem('KPR / KIR (!)', 'Pojedinačna evidencija PDV', 3, 18, 0),
    MenuItem('KPR / KIR (!)', 'E-Otpremnice', 3, 19, 0),
    MenuItem('KPR / KIR (!)', 'E-Fakture - Poslate', 3, 20, 0),
    # Veleprodaja
    MenuItem('Veleprodaja', 'Ulazi', 4, 1, 0),
    MenuItem('Veleprodaja', 'Izlazi', 4, 2, 0),
    MenuItem('Veleprodaja', 'Predračuni, reversi', 4, 3, 0),
    MenuItem('Veleprodaja', 'Mesečno fakturisanje', 4, 4, 0),
    MenuItem('Veleprodaja', 'Porudžbine dobavljačima', 4, 5, 0),
    MenuItem('Veleprodaja', 'Popisi', 4, 6, 0),
    MenuItem('Veleprodaja', 'Kritične zalihe', 4, 7, 0),
    MenuItem('Veleprodaja', 'Politika cena', 4, 9, 0),
    MenuItem('Veleprodaja', 'Cenovnici', 4, 10, 0),
    MenuItem('Veleprodaja', 'Izveštaji', 4, 12, 0),
    # Maloprodaja
    MenuItem('Maloprodaja', 'Ulazi', 5, 1, 0),
    MenuItem('Maloprodaja', 'Izlazi', 5, 2, 0),
    MenuItem('Maloprodaja', 'Porudžbine dobavljačima', 5, 3, 0),
    MenuItem('Maloprodaja', 'Predračuni, reversi', 5, 4, 0),
    MenuItem('Maloprodaja', 'Nivelacije', 5, 5, 0),
    MenuItem('Maloprodaja', 'Čekovi', 5, 6, 0),
    MenuItem('Maloprodaja', 'Popisi', 5, 7, 0),
    MenuItem('Maloprodaja', 'Kartice', 5, 8, 0),
    MenuItem('Maloprodaja', 'Raspored artikala', 5, 9, 0),
    MenuItem('Maloprodaja', 'Raspored stolova', 5, 10, 0),
    MenuItem('Maloprodaja', 'Nadgledanje stolova', 5, 11, 0),
    MenuItem('Maloprodaja', 'Kasiri', 5, 12, 0),
    MenuItem('Maloprodaja', 'Politika cena', 5, 13, 0),
    MenuItem('Maloprodaja', 'Kritične zalihe', 5, 14, 0),
    MenuItem('Maloprodaja', 'Izveštaji', 5, 16, 0),
    # Proizvodnja
    MenuItem('Proizvodnja', 'Ulazi', 6, 1, 0),
    MenuItem('Proizvodnja', 'Izlazi', 6, 2, 0),
    MenuItem('Proizvodnja', 'Porudžbine dobavljačima', 6, 3, 0),
    MenuItem('Proizvodnja', 'Predračuni, reversi', 6, 4, 0),
    MenuItem('Proizvodnja', 'Popisi', 6, 5, 0),
    MenuItem('Proizvodnja', 'Radni nalozi', 6, 6, 0),
    MenuItem('Proizvodnja', 'Plan proizvodnje', 6, 7, 0),
    MenuItem('Proizvodnja', 'Kritične zalihe', 6, 8, 0),
    MenuItem('Proizvodnja', 'Politika cena', 6, 10, 0),
    MenuItem('Proizvodnja', 'Cenovnici', 6, 11, 0),
    MenuItem('Proizvodnja', 'Izveštaji', 6, 13, 0),
    # Ostalo (!)
    MenuItem('Ostalo (!)', 'Dodela šifara i brojeva dokumenata', 7, 1, 0),
    MenuItem('Ostalo (!)', 'Izvoz podataka', 7, 2, 1),
]


def find(path: str) -> MenuItem:
    """The menu item for a path like "Registri > Komitenti"."""
    for item in MENU:
        if item.path == path:
            return item
    raise LookupError(f"Nepoznata stavka menija: {path}")
