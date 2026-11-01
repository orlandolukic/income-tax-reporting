import { createContext, Fragment, useContext, useState } from "react";

/** Individual entries of a konto, read from its card (setting "Pojedinačni iznosi po kontu"). */
export type KontoItems = {
  greska?: string; // the card couldn't be opened / read
  kolone?: string[]; // the card's columns
  redovi?: { kolone: Record<string, string>; duguje: number; potrazuje: number; iznos: number }[];
  broj?: number;
  van_perioda?: number; // rows of other months the card showed, left out
  duguje?: number;
  potrazuje?: number;
  kolona_duguje?: string;
  kolona_potrazuje?: string;
  slaze?: boolean; // the sums equal the konto's
};

type Konto = { konto: string; naziv: string; duguje: number; potrazuje: number; saldo: number; stavke?: KontoItems };

/** Value of the "Promet u poslednjih 12 meseci" report (tim_automation/reports/turnover.py). */
export type TurnoverMonth = {
  mesec: string; // "2026-10"
  naziv: string; // "Oktobar 2026"
  godina: string;
  od: string; // "01/10/2026"
  do: string;
  status: "ceka" | "radi" | "ok" | "nedostupno";
  osnova?: number | null; // amount on the konto range (Potražuje, or Potražuje − Duguje); older results: potrazuje
  potrazuje: number | null; // Potražuje on the konto range
  izuzeto: number | null; // Potražuje on konto 6050 (export), not counted
  promet: number | null; // potrazuje - izuzeto
  duguje: number | null;
  konta: Konto[];
  konta_potpuna: boolean | null; // all konta were shown in the site's table
  napomena: string;
};

export type TurnoverValue = {
  od: string;
  do: string;
  danas: string;
  limit: number;
  izuzet_konto: string; // the excluded konta, joined ("6050")
  izuzeta?: string[];
  kolona?: string; // header of the amount column, e.g. "Potražuje 6–65"
  broj_meseci?: number;
  konto_od?: string;
  konto_do?: string;
  iznos?: string;
  meseci: TurnoverMonth[];
  napomene: string[];
  klijenti?: boolean; // setting "Računi veleprodaje po klijentima"
  racuni?: Invoice[];
  nalozi?: Record<string, Order>; // by orderKey
  po_klijentima?: Client[];
  racuni_godine?: Record<string, { u_listi?: number; u_periodu?: number; greska?: string }>;
  ukupno: { promet: number; izuzeto: number; osnova?: number; potrazuje: number; meseci: number };
  preostalo: number;
  procenat: number;
  prekoracen: boolean;
  potpun: boolean;
};

/** A Veleprodaja › Izlazi invoice (tim_automation/pages/izlazi_vp.py). */
export type Invoice = {
  godina: string;
  dokument: string;
  datum: string;
  vrsta: string;
  komitent: string;
  naziv: string;
  status: string;
  iznos: number;
  nalog: string; // "VIED00323"
  greska: string;
  polja?: Record<string, string>;
  stavke?: { kolone: string[]; redovi: Record<string, string>[] };
};

/** A financial order read from an invoice's link: its konta. */
export type Order = {
  broj: string;
  greska?: string;
  polja?: Record<string, string>;
  kolone?: string[];
  redovi?: Record<string, string>[];
  duguje?: number;
  potrazuje?: number;
};

export type Client = {
  sifra: string;
  naziv: string;
  promet: number;
  izuzeto: number;
  broj_racuna: number;
  iznos_racuna: number;
  racuni: number[]; // indexes in value.racuni
  stavke: { mesec: string; konto: string; nalog: string; iznos: number; izuzeto: boolean; racun: number | null }[];
};

const BEZ_RACUNA = "Bez računa veleprodaje";

/** "VIED00323", "VIED 323" -> "VIED323" (as izlazi_vp.order_key). */
export function orderKey(text: string): string {
  const m = /^\s*([A-Za-zČĆŽŠĐčćžšđ]+)\s*0*(\d+)\s*$/.exec(text ?? "");
  return m ? `${m[1].toUpperCase()}${Number(m[2])}` : "";
}

const OrdersContext = createContext<Record<string, Order>>({});

/** An order number; hovering it shows the order's konta (read during the run). */
function OrderRef({ text }: { text: string }) {
  const orders = useContext(OrdersContext);
  const [shown, setShown] = useState<{ left: number; top: number } | null>(null);
  const order = orders[orderKey(text)];
  if (!order) return <>{text}</>;
  return (
    <span
      className="order-ref"
      onMouseEnter={(e) => {
        const r = e.currentTarget.getBoundingClientRect();
        setShown({ left: Math.max(8, Math.min(r.left, window.innerWidth - 380)), top: r.bottom + 4 });
      }}
      onMouseLeave={() => setShown(null)}
    >
      {text}
      {shown && (
        <span className="order-pop" role="tooltip" style={shown}>
          <span className="order-pop-title">
            Finansijski nalog {order.broj}
            {order.polja?.Datum && <span className="muted"> · {order.polja.Datum}</span>}
          </span>
          {order.greska ? (
            <span className="error small">{order.greska}</span>
          ) : (
            <table className="konta-table">
              <thead>
                <tr>
                  <th>Konto</th>
                  <th>Analitika</th>
                  <th className="amount">Duguje</th>
                  <th className="amount">Potražuje</th>
                </tr>
              </thead>
              <tbody>
                {(order.redovi ?? []).map((r, i) => (
                  <tr key={i}>
                    <td>{r.Konto}</td>
                    <td>{r.Analitka ?? r.Analitika}</td>
                    <td className="amount">{r.Duguje}</td>
                    <td className="amount">{r["Potražuje"]}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </span>
      )}
    </span>
  );
}

export function formatRsd(n: number | null | undefined): string {
  if (n == null) return "";
  return n.toLocaleString("sr-Latn", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

const dots = (date: string) => date.replaceAll("/", ".") + ".";

export default function TurnoverView({ value, running }: { value: TurnoverValue; running: boolean }) {
  const [open, setOpen] = useState<string | null>(null);
  const [openKonto, setOpenKonto] = useState<string | null>(null);
  const { ukupno, limit } = value;
  const excluded = value.izuzet_konto;
  const excludedList = value.izuzeta ?? (excluded ? [excluded] : []);
  const isExcluded = (konto: string) => excludedList.some((k) => konto.startsWith(k));
  const excludedHeader = excludedList.length ? `Konto ${excluded} (izuzeto)` : "Izuzeto";
  const level = value.prekoracen ? "over" : value.procenat >= 80 ? "near" : "ok";
  let cumulative = 0;

  return (
    <OrdersContext.Provider value={value.nalozi ?? {}}>
    <div className="turnover">
      <div className="turnover-tiles">
        <div className="tile">
          <div className="tile-label">Promet u poslednjih {value.broj_meseci ?? value.meseci.length} meseci</div>
          <div className="tile-value">{formatRsd(ukupno.promet)} RSD</div>
          <div className="muted small">
            {value.meseci[0]?.naziv} – {value.meseci[value.meseci.length - 1]?.naziv}
            {!value.potpun && ` · pročitano ${ukupno.meseci} od ${value.meseci.length} meseci`}
          </div>
        </div>
        <div className="tile">
          <div className="tile-label">Limit (Zakon o PDV)</div>
          <div className="tile-value">{formatRsd(limit)} RSD</div>
        </div>
        <div className={`tile tile-${level}`}>
          <div className="tile-label">{value.prekoracen ? "Prekoračeno za" : "Preostalo do limita"}</div>
          <div className="tile-value">{formatRsd(Math.abs(value.preostalo))} RSD</div>
          <div className="small">{value.procenat.toLocaleString("sr-Latn")} % limita</div>
        </div>
      </div>
      <div className={`limit-meter meter-${level}`} role="meter" aria-valuenow={value.procenat} aria-valuemin={0} aria-valuemax={100}>
        <span style={{ width: `${Math.min(value.procenat, 100)}%` }} />
      </div>
      {!value.potpun && !running && (
        <p className="warning small">Nisu pročitani svi meseci: ukupan promet je nepotpun (vidi napomene).</p>
      )}

      <div className="table-wrap tall">
        <table className="turnover-table">
          <thead>
            <tr>
              <th>Mesec</th>
              <th>Period</th>
              <th className="amount">{value.kolona ?? "Potražuje 6–7"}</th>
              <th className="amount">{excludedHeader}</th>
              <th className="amount">Promet</th>
              <th className="amount">Kumulativno</th>
            </tr>
          </thead>
          <tbody>
            {value.meseci.map((m) => {
              if (m.promet != null) cumulative += m.promet;
              const canOpen = m.konta.length > 0;
              return (
                <Fragment key={m.mesec}>
                  <tr
                    className={`m-${m.status} ${open === m.mesec ? "selected" : ""}`}
                    onClick={() => canOpen && setOpen(open === m.mesec ? null : m.mesec)}
                    title={canOpen ? "Prikaži konta" : undefined}
                  >
                    <td>
                      {canOpen && <span className="caret">{open === m.mesec ? "▾" : "▸"}</span>}
                      {m.naziv}
                    </td>
                    <td className="muted small">
                      {dots(m.od)} – {dots(m.do)}
                    </td>
                    {m.status === "ok" ? (
                      <>
                        <td className="amount">{formatRsd(m.osnova ?? m.potrazuje)}</td>
                        <td className={`amount ${m.izuzeto ? "excluded" : "muted"}`}>{formatRsd(m.izuzeto)}</td>
                        <td className="amount strong">{formatRsd(m.promet)}</td>
                        <td className="amount muted">{formatRsd(cumulative)}</td>
                      </>
                    ) : (
                      <td colSpan={4} className="muted small">
                        {m.status === "radi" ? (
                          <>
                            <span className="spinner small" /> čita se…
                          </>
                        ) : m.status === "nedostupno" ? (
                          <span className="warning">Nije pročitano: {m.napomena}</span>
                        ) : running ? (
                          "čeka"
                        ) : (
                          "nije pročitano"
                        )}
                      </td>
                    )}
                  </tr>
                  {open === m.mesec && (
                    <tr className="konta-row">
                      <td colSpan={6}>
                        <table className="konta-table">
                          <thead>
                            <tr>
                              <th>Konto</th>
                              <th>Naziv</th>
                              <th className="amount">Duguje</th>
                              <th className="amount">Potražuje</th>
                            </tr>
                          </thead>
                          <tbody>
                            {m.konta.map((k) => {
                              const id = `${m.mesec}/${k.konto}`;
                              const st = k.stavke;
                              const isOpen = openKonto === id && !!st;
                              return (
                                <Fragment key={k.konto}>
                                  <tr
                                    className={`${isExcluded(k.konto) ? "excluded" : ""} ${st ? "clickable" : ""} ${isOpen ? "selected" : ""}`}
                                    onClick={() => st && setOpenKonto(isOpen ? null : id)}
                                    title={st ? "Prikaži pojedinačne iznose" : undefined}
                                  >
                                    <td>
                                      {st && <span className="caret">{isOpen ? "▾" : "▸"}</span>}
                                      {k.konto}
                                    </td>
                                    <td>
                                      {k.naziv}
                                      {isExcluded(k.konto) && <span className="badge">izuzeto</span>}
                                      {st?.greska && <span className="badge badge-error">nije pročitano</span>}
                                      {st && !st.greska && (
                                        <span className={`badge ${st.slaze ? "badge-items" : "badge-warning"}`}>
                                          {items(st.broj ?? 0)}{st.slaze ? "" : " · zbir se ne slaže"}
                                        </span>
                                      )}
                                    </td>
                                    <td className="amount">{formatRsd(k.duguje)}</td>
                                    <td className="amount">{formatRsd(k.potrazuje)}</td>
                                  </tr>
                                  {isOpen && (
                                    <tr className="items-row">
                                      <td colSpan={4}>
                                        <KontoItemsTable konto={k} />
                                      </td>
                                    </tr>
                                  )}
                                </Fragment>
                              );
                            })}
                          </tbody>
                        </table>
                        {m.konta_potpuna === false && (
                          <p className="muted small">
                            Tabela na sajtu nije prikazala sva konta; izuzeta konta ({excluded}) su pročitana posebnom pretragom.
                          </p>
                        )}
                        {m.status === "ok" && m.napomena && <p className="warning small">{m.napomena}</p>}
                      </td>
                    </tr>
                  )}
                </Fragment>
              );
            })}
          </tbody>
          <tfoot>
            <tr>
              <th colSpan={2}>Ukupno</th>
              <th className="amount">{formatRsd(ukupno.osnova ?? ukupno.potrazuje)}</th>
              <th className="amount">{formatRsd(ukupno.izuzeto)}</th>
              <th className="amount">{formatRsd(ukupno.promet)}</th>
              <th />
            </tr>
          </tfoot>
        </table>
      </div>

      {value.klijenti && <ClientsSection value={value} />}

      <ul className="report-notes small">
        {value.napomene.map((n, i) => (
          <li key={i} className={i === 0 ? "note-excluded" : "muted"}>
            {n}
          </li>
        ))}
      </ul>
    </div>
    </OrdersContext.Provider>
  );
}

function ClientsSection({ value }: { value: TurnoverValue }) {
  const [open, setOpen] = useState<string | null>(null);
  const clients = value.po_klijentima ?? [];
  const invoices = value.racuni ?? [];
  const years = Object.entries(value.racuni_godine ?? {});
  const total = clients.reduce((t, c) => t + c.promet, 0);
  return (
    <section className="clients">
      <h3>Promet po klijentima</h3>
      <p className="muted small">
        {invoices.length} izlaznih računa veleprodaje
        {years.map(([y, g]) => (g.greska ? ` · ${y}: nije pročitano (${g.greska})` : ` · ${y}: ${g.u_periodu} od ${g.u_listi} u periodu`))}
        {" · "}pređite mišem preko broja naloga za njegova konta.
      </p>
      <div className="table-wrap tall">
        <table className="turnover-table">
          <thead>
            <tr>
              <th>Komitent</th>
              <th>Naziv</th>
              <th className="amount">Računa</th>
              <th className="amount">Iznos računa</th>
              <th className="amount">Izuzeto</th>
              <th className="amount">Promet</th>
            </tr>
          </thead>
          <tbody>
            {clients.map((c) => {
              const id = c.sifra || c.naziv;
              const isOpen = open === id;
              return (
                <Fragment key={id}>
                  <tr className={`${isOpen ? "selected" : ""} ${c.naziv === BEZ_RACUNA ? "muted" : ""}`} onClick={() => setOpen(isOpen ? null : id)}>
                    <td>
                      <span className="caret">{isOpen ? "▾" : "▸"}</span>
                      {c.sifra}
                    </td>
                    <td>{c.naziv}</td>
                    <td className="amount">{c.broj_racuna || ""}</td>
                    <td className="amount">{c.broj_racuna ? formatRsd(c.iznos_racuna) : ""}</td>
                    <td className={`amount ${c.izuzeto ? "excluded" : "muted"}`}>{formatRsd(c.izuzeto)}</td>
                    <td className="amount strong">{formatRsd(c.promet)}</td>
                  </tr>
                  {isOpen && (
                    <tr className="konta-row">
                      <td colSpan={6}>
                        <ClientDetails client={c} invoices={invoices} />
                      </td>
                    </tr>
                  )}
                </Fragment>
              );
            })}
          </tbody>
          <tfoot>
            <tr>
              <th colSpan={5}>Ukupno (stavke kartica)</th>
              <th className="amount">{formatRsd(total)}</th>
            </tr>
          </tfoot>
        </table>
      </div>
    </section>
  );
}

function ClientDetails({ client, invoices }: { client: Client; invoices: Invoice[] }) {
  const [openInvoice, setOpenInvoice] = useState<number | null>(null);
  return (
    <div className="client-details">
      {client.racuni.length > 0 && (
        <table className="konta-table">
          <thead>
            <tr>
              <th>Račun</th>
              <th>Datum</th>
              <th>Vrsta</th>
              <th>Status</th>
              <th>Finansijski nalog</th>
              <th className="amount">Prod. vred.</th>
            </tr>
          </thead>
          <tbody>
            {client.racuni.map((i) => {
              const inv = invoices[i];
              const isOpen = openInvoice === i;
              return (
                <Fragment key={i}>
                  <tr className={`clickable ${isOpen ? "selected" : ""}`} onClick={() => setOpenInvoice(isOpen ? null : i)}>
                    <td>
                      <span className="caret">{isOpen ? "▾" : "▸"}</span>
                      {inv.dokument}
                      {inv.greska && <span className="badge badge-error">greška</span>}
                    </td>
                    <td>{inv.datum}</td>
                    <td>{inv.vrsta}</td>
                    <td>{inv.status}</td>
                    <td>{inv.nalog && <OrderRef text={inv.nalog} />}</td>
                    <td className="amount">{formatRsd(inv.iznos)}</td>
                  </tr>
                  {isOpen && (
                    <tr className="items-row">
                      <td colSpan={6}>
                        <InvoiceDetails invoice={inv} />
                      </td>
                    </tr>
                  )}
                </Fragment>
              );
            })}
          </tbody>
        </table>
      )}
      {client.stavke.length > 0 && (
        <>
          <p className="small strong">Stavke kartica ({items(client.stavke.length)})</p>
          <table className="konta-table">
            <thead>
              <tr>
                <th>Mesec</th>
                <th>Konto</th>
                <th>Nalog</th>
                <th>Račun</th>
                <th className="amount">Iznos</th>
              </tr>
            </thead>
            <tbody>
              {client.stavke.map((st, i) => (
                <tr key={i} className={st.izuzeto ? "excluded" : ""}>
                  <td>{st.mesec}</td>
                  <td>
                    {st.konto}
                    {st.izuzeto && <span className="badge">izuzeto</span>}
                  </td>
                  <td>{st.nalog && <OrderRef text={st.nalog} />}</td>
                  <td>{st.racun != null ? invoices[st.racun]?.dokument : ""}</td>
                  <td className="amount">{formatRsd(st.iznos)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </>
      )}
    </div>
  );
}

function InvoiceDetails({ invoice }: { invoice: Invoice }) {
  if (invoice.greska) return <p className="error small">{invoice.greska}</p>;
  const fields = Object.entries(invoice.polja ?? {}).filter(([, v]) => v);
  const st = invoice.stavke;
  return (
    <div className="invoice-details">
      {st && st.redovi.length > 0 && (
        <table className="konta-table">
          <thead>
            <tr>
              {st.kolone.map((c) => (
                <th key={c} className={["Kol.", "Cena", "Iznos"].includes(c) ? "amount" : ""}>
                  {c}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {st.redovi.map((r, i) => (
              <tr key={i}>
                {st.kolone.map((c) => (
                  <td key={c} className={["Kol.", "Cena", "Iznos"].includes(c) ? "amount" : ""}>
                    {r[c]}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      )}
      <dl className="invoice-fields small">
        {fields.map(([k, v]) => (
          <Fragment key={k}>
            <dt>{k}</dt>
            <dd>{v}</dd>
          </Fragment>
        ))}
      </dl>
    </div>
  );
}

function KontoItemsTable({ konto }: { konto: Konto }) {
  const st = konto.stavke!;
  if (st.greska) return <p className="error small">{st.greska}</p>;
  const columns = st.kolone ?? [];
  const amounts = new Set([st.kolona_duguje, st.kolona_potrazuje].filter(Boolean));
  const isAmount = (c: string) => amounts.has(c) || /saldo|iznos/i.test(c);
  return (
    <div className="konto-items">
      <div className="table-wrap">
        <table className="konta-table">
          <thead>
            <tr>
              {columns.map((c) => (
                <th key={c} className={isAmount(c) ? "amount" : ""}>
                  {c}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {(st.redovi ?? []).map((r, i) => (
              <tr key={i}>
                {columns.map((c) => (
                  <td key={c} className={isAmount(c) ? "amount" : ""}>
                    <OrderRef text={r.kolone[c]} />
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className={`small ${st.slaze ? "muted" : "warning"}`}>
        {items(st.broj ?? 0)} · zbir: duguje {formatRsd(st.duguje)}, potražuje {formatRsd(st.potrazuje)}
        {st.slaze
          ? " · slaže se sa kontom"
          : ` · ne slaže se sa kontom (duguje ${formatRsd(konto.duguje)}, potražuje ${formatRsd(konto.potrazuje)})`}
        {!!st.van_perioda && ` · van meseca izostavljeno: ${items(st.van_perioda)}`}
      </p>
    </div>
  );
}

/** "1 stavka", "3 stavke", "5 stavki", "21 stavka" (Serbian plural). */
function items(n: number): string {
  const last = n % 10, lastTwo = n % 100;
  const word = last === 1 && lastTwo !== 11 ? "stavka" : last >= 2 && last <= 4 && (lastTwo < 12 || lastTwo > 14) ? "stavke" : "stavki";
  return `${n} ${word}`;
}
