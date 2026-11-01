import { useEffect, useState } from "react";

export type Company = { name: string; pib: string; active: boolean };

export type Prompt =
  | { id: number; kind: "login"; data: { username: string; message: string } }
  | { id: number; kind: "wait"; data: { message: string } }
  | {
      id: number;
      kind: "company";
      data: {
        companies: Company[];
        years: string[];
        year: string;
        selected: number;
        savedAt: number | null; // when the list was read from the site (Unix seconds)
        message: string;
        // Years confirmed in the browser, by company index.
        checked: Record<string, { years: string[]; year: string; error?: string }>;
        inBrowser: number; // company currently selected in the browser
      };
    }
  | { id: number; kind: "ready"; data: { company: string } }
  | { id: number; kind: "done"; data: { error?: string } };

// --- Jobs (see tim_automation/jobs) ---------------------------------------------------------------

export type ParamSpec = {
  name: string;
  label: string;
  kind: "text" | "number" | "select" | "menu" | "column" | "filters" | "bool" | "conditions" | "task" | "dataset" | "date" | "textarea" | "choice" | "secret";
  options: string[];
  default: string;
  help: string;
  required: boolean;
  allow_ref: boolean; // the value can come from an earlier task's result
  row_column: string; // in a subtask, empty = this column of the current row
  show_if: [string, string] | null; // shown only when that other param has that value
  fields?: FilterField[]; // kind "filters": the fields to offer (else the page's "Napredni filteri")
  depends?: string; // kind "choice": the param whose value decides the options (e.g. "vrsta")
  choices?: string; // kind "choice": which options, in JobsState.choices (e.g. "podvrste")
  group?: string; // section of the task's form ("" = above the sections)
};

/** A param value taken from an earlier task's result (resolved by the runner when the task starts). */
export type ParamRef = {
  ref: string; // id of the earlier task, or "@red" = the row a subtask runs for
  pick: "first" | "row" | "all" | "count" | "total" | "value" | "current";
  column?: string;
  row?: number; // for pick "row", from 1
};

/** One advanced filter of a "Pretraga" task (see tim_automation/pages/filters.py). */
export type FilterValue = {
  polje: string; // e.g. "racun.Datum"
  operator: string;
  vrednost?: string | ParamRef;
  do?: string | ParamRef; // second value for "Između"
  izbor?: string[]; // list filters
};

/** One check of a "Uslov" task: a value from an earlier task, an operator and what it is compared with. */
export type CheckValue = {
  levo: ParamRef | string;
  operator: string;
  vrednost?: string | ParamRef;
  do?: string | ParamRef; // second value for "Između"
  vrsta?: string; // "Automatski" | "Tekst" | "Broj" | "Datum"
};

export type ParamValue = string | boolean | ParamRef | FilterValue[] | CheckValue[] | SecretValue;

/** A "secret" param (e.g. a PIN): the job holds only the id of the value kept in the OS credential store; `value` is
 * a newly typed one, sent once with "Sačuvaj" (the server stores it and keeps only the new id). */
export type SecretValue = { secret: string; value?: string };

export const isSecret = (v: ParamValue | undefined): v is SecretValue =>
  typeof v === "object" && v !== null && !Array.isArray(v) && "secret" in v;

export const isRef = (v: ParamValue | undefined): v is ParamRef =>
  typeof v === "object" && v !== null && !Array.isArray(v) && "ref" in v;

export type TaskType = {
  id: string;
  title: string;
  description: string;
  implemented: boolean;
  outputColumns: string[]; // columns of the rows it returns, when known in advance
  returnsRows: boolean; // can have subtasks
  totals: string[]; // names of the totals it returns
  breakerWhen: string; // non-empty: can be a "prekidač"; says when its condition is not met
  subtasksWhen: [string, unknown] | null; // subtasks run once (e.g. on an opened page) when param == value
  subtasksOnce: boolean; // subtasks always run once after it (it opens a page)
  columnKinds?: Record<string, "number" | "date">; // known number / date columns of its rows
  group?: string; // group in the lists of task types, e.g. "PURS – Poreska uprava (ePorezi)"
  params: ParamSpec[];
};

export type Task = {
  id: string;
  type: string;
  title: string;
  params: Record<string, ParamValue>;
  subtasks?: Task[]; // run for each row of this task's result
  breaker?: boolean; // "prekidač": see TaskType.breakerWhen
  // "Uslov": tasks run when it is met (AKO), its INAČE AKO branches and the tasks run when none is met.
  then?: Task[];
  elifs?: Branch[];
  else?: Task[];
};

/** An INAČE AKO branch of a "Uslov": its own checks (same params as the condition) and tasks. */
export type Branch = { id: string; params: Record<string, ParamValue>; then: Task[] };

/** Tasks nested in a task, in the order they are numbered ("3.1", "3.2", ...): its subtasks, then the
 * tasks of a condition's branches (AKO, each INAČE AKO, INAČE). Same as store.children in Python. */
export function children(task: Task): Task[] {
  return [
    ...(task.subtasks ?? []),
    ...(task.then ?? []),
    ...(task.elifs ?? []).flatMap((b) => b.then),
    ...(task.else ?? []),
  ];
}

export const newId = () => Math.random().toString(16).slice(2, 10);

/** A new task of this type with default params (a condition also gets its empty branches). */
export function newTask(type: TaskType): Task {
  const params = Object.fromEntries(type.params.map((p) => [p.name, p.default]));
  const task: Task = { id: newId(), type: type.id, title: "", params };
  return type.id === "condition" ? { ...task, then: [], elifs: [], else: [] } : task;
}

export type Job = { id: string; name: string; description: string; tasks: Task[]; updated_at: number };

export type TaskStatus = "pending" | "running" | "done" | "failed" | "not_implemented" | "skipped" | "cancelled"; // cancelled: "Zaustavi" while the task was waiting

export type TaskResult = {
  id: string;
  type: string;
  title: string;
  status: TaskStatus;
  value: unknown;
  error: string;
  progress?: string; // e.g. "Pročitano 1200 / 4260 redova" while running
  errors?: string[]; // subtasks: one message per failed row
  napomena?: string; // e.g. a breaker stopped the job / skipped rows
  aktivan?: boolean; // being computed right now
  red_napredak?: [number, number]; // its subtasks are running for row i of n
  grane?: Record<string, number>; // "Uslov": how many times each branch ran ("then", INAČE AKO id, "else")
  subtasks?: TaskResult[];
  started_at: number | null;
  finished_at: number | null;
};

export type RunStatus = "running" | "done" | "failed" | "cancelled" | "stopped";

export type Run = {
  job_id: string;
  status: RunStatus;
  started_at: number;
  finished_at: number | null;
  tasks: TaskResult[];
  napomena?: string; // why the job stopped (a condition in a subtask)
  aktivno?: { id: string; red: string }; // while running: the task being computed and its row label
  koraci?: number; // steps recorded so far ("Summary", jobs/RunReport.tsx)
  koraci_fajl?: string; // the saved report (data/results/<name>.json|csv)
};

export type FilterField = {
  id: string;
  naziv: string;
  vrsta: "text" | "date" | "number" | "list" | "bool";
  operatori: string[];
  opcije?: string[];
};

/** What is known about a page (from saved HTML or an "Otvori stranicu" run), by menu path. */
export type PageInfo = {
  naslov: string;
  filter: boolean;
  tabele: { id: string; naziv: string; kolone: string[] }[];
  filteri?: FilterField[]; // fields of the "Napredni filteri" window
  izvor?: string;
  vreme?: number;
};

export type JobsState = {
  pages: Record<string, PageInfo>;
  jobs: Job[];
  runs: Record<string, Run>; // last run per job id
  company: { key: string; label: string } | null; // whose jobs these are (each company has its own)
  choices: Record<string, Record<string, string[]>>; // options known in the code, e.g. podvrste[vrsta]
  taskTypes: TaskType[];
  runner: { ready: boolean; status: string; running: string | null; queued: string[] };
};

/** Who is logged in and which company is open (from main.py). */
export type Session = {
  user: string;
  company: { name?: string; pib?: string; year?: string; active?: boolean; naSajtu?: string } | null;
};

// --- Reports ("Izveštaji", see tim_automation/reports) -------------------------------------------

export type ReportSetting = {
  name: string;
  label: string;
  kind: "text" | "number" | "bool" | "select";
  default: string | boolean;
  options: string[];
  help: string;
};

export type ReportTypeInfo = {
  id: string;
  title: string;
  description: string;
  notes: string[];
  settings: ReportSetting[]; // what ⚙ lets the user set, with defaults
};

export type ReportResult = {
  id: string;
  report: string;
  title: string;
  status: "running" | "done" | "failed" | "cancelled";
  started_at: number;
  finished_at: number | null;
  progress: string;
  error: string;
  value: unknown; // report-specific (e.g. TurnoverValue)
  fajl: string; // CSV copy at /files/izvestaji/<fajl>
  firma: string;
  podesavanja?: Record<string, string | boolean>; // the settings it was made with
};

export type ReportsState = {
  types: ReportTypeInfo[];
  company: { key: string; label: string } | null;
  history: Record<string, ReportResult[]>; // newest first, per report id
  settings: Record<string, Record<string, string | boolean>>; // this company's settings per report id
  current: ReportResult | null;
  runner: { ready: boolean; running: string | null; queued: string[] };
};

export type Shared = {
  jobs?: JobsState;
  session?: Session;
  reports?: ReportsState;
  purs?: PursState;
  purs_prijava?: PursLogin;
  purs_red?: PursQueueState;
  pocetna?: { tim: HomeCheck; purs: HomeCheck };
};

/** A check on the "Početna" page (tim_automation/home_status.py). */
export type HomeCheck = {
  stanje: "" | "provera" | "ok" | "odjavljen" | "greska" | "nepoznato";
  poruka: string;
  provereno: number | null;
  obveznik?: { PIB: string; Naziv: string } | null; // ePorezi: the taxpayer chosen in this browser
};

/** The open company's job runs (`/api/pocetna/stats`). */
export type HomeStats = {
  poslova: number;
  dana: number;
  pokretanja: number;
  danas: number;
  po_statusu: Partial<Record<RunStatus, number>>;
  koraka: number;
  prosek: number | null; // seconds
  poslednja: { posao: string; id: string; status: RunStatus; pocetak: number; kraj: number | null; fajl: string; koraci: number; greske: number }[];
};

/** An ePorezi "Upit stanja" request (tim_automation/purs_reports.py). */
export type PursRequest = {
  id: string;
  status: "ceka" | "gotovo" | "greska" | "prekinuto";
  status_tekst?: string;
  sajt_id?: string; // ID of the request on ePorezi (first column of the "Упит стања" table)
  poslato: number;
  zavrseno?: number;
  "Tip zahteva": string;
  kod?: string; // short code of the type: sintetika, analitika-PDV, nalog-xml, zahtev-<ID> (sent by hand)
  Grupa?: string;
  PIB?: string;
  Naziv?: string;
  posao?: string;
  red?: Record<string, string>; // first row of the requests table on ePorezi
  provera?: number;
  provera_broj?: number;
  fajl: string;
  velicina?: number;
  greska: string;
  firma_naziv?: string; // the company open in TiM when it was sent
  ponovo_trazen?: number; // last time an "Upit stanja" got this report again (the site makes one of a type per day)
  napomena?: string;
};

/** "Prijava na ePorezi" on the PURS page (tim_automation/purs_login.py). */
export type PursLogin = {
  stanje: "" | "radi" | "gotovo" | "greska";
  poruka: string;
  napredak: string;
  obveznik: { PIB: string; Naziv: string } | null;
  vreme: number | null;
  izdavalac: string;
  citac: string;
  pin: string; // where the PIN comes from: "stranica", "posao „…“" or "" (none)
  pib_firme: string;
  spremno: boolean; // a company is open and the program is ready
  email: string; // e-mail for requests sent from the PURS page
  akcija: "" | "login" | "taxpayer" | "request"; // what the PURS page asked for last
  zahtev: string | null; // the request it sent (our id)
};

/** One item of the PURS queue (tim_automation/purs_queue.py): everything that uses the one ePorezi session. */
export type PursQueueItem = {
  id: string;
  vrsta: "prijava" | "obveznik" | "zahtev" | "provera" | "sesija";
  naziv: string;
  pib: string;
  izvor: string; // who scheduled it: "Stranica PURS", "Posao „…“", "Čekanje izveštaja", "Početna"
  firma: string;
  opis: string;
  dodato: number;
  pocetak: number | null;
  kraj: number | null;
  status: "zakazano" | "radi" | "gotovo" | "greska" | "otkazano";
  poruka: string;
  napredak: string;
};

/** A taxpayer whose reports are waited for: checked in turns (one check, then the next taxpayer). */
export type PursQueueTaxpayer = { pib: string; naziv: string; zahtevi: string[]; poslednja: number | null };

export type PursQueueState = {
  trenutno: PursQueueItem | null;
  red: PursQueueItem[]; // scheduled, in order
  istorija: PursQueueItem[]; // finished, newest first
  sesija: { pregledac: boolean; prijavljen: boolean | null; obveznik: { PIB: string; Naziv: string } | null; provereno: number | null };
  obveznici: PursQueueTaxpayer[];
  sada: number; // server time when published
  poll: number; // seconds between a taxpayer's checks
};

/** Requests of the company open in TiM (`firma` = its label, null: no company open). */
export type PursState = { firma: string | null; zahtevi: PursRequest[] };

type Message =
  | { type: "state"; status: string; prompt: Prompt | null; build?: string }
  | { type: "log"; text: string; reset?: boolean }
  | { type: "shared"; key: keyof Shared; value: never };

const MAX_LOG = 200_000;

/** This page's own script, e.g. "/assets/index-YPQpkkJ1.js" ("" in the dev server, where nothing is compared). */
const OWN_SCRIPT = import.meta.url.includes("/assets/") ? new URL(import.meta.url).pathname : "";

/** Reload for this build, once (if it still differs afterwards, something else is wrong: never loop). */
function reloadOnce(build: string): boolean {
  try {
    if (sessionStorage.getItem("reloadedFor") === build) return false;
    sessionStorage.setItem("reloadedFor", build);
  } catch {
    return false;
  }
  window.location.reload();
  return true;
}

/** Live state from the Python server: status line, open prompt, console log and shared state (jobs). */
export function useServer() {
  const [status, setStatus] = useState("");
  const [prompt, setPrompt] = useState<Prompt | null>(null);
  const [log, setLog] = useState("");
  const [shared, setShared] = useState<Shared>({});
  const [connected, setConnected] = useState(false);

  useEffect(() => {
    const events = new EventSource("/api/events");
    events.onopen = () => setConnected(true);
    events.onerror = () => setConnected(false);
    events.onmessage = (e) => {
      const msg: Message = JSON.parse(e.data);
      if (msg.type === "state") {
        // The program serves a newer page (it was updated and restarted while this tab stayed open): load it.
        if (msg.build && OWN_SCRIPT && msg.build !== OWN_SCRIPT && reloadOnce(msg.build)) return;
        setStatus(msg.status);
        setPrompt(msg.prompt);
      } else if (msg.type === "shared") {
        setShared((old) => ({ ...old, [msg.key]: msg.value }));
      } else {
        setLog((old) => (msg.reset ? msg.text : old + msg.text).slice(-MAX_LOG));
      }
    };
    return () => events.close();
  }, []);

  return { status, prompt, log, shared, connected };
}

export function answer(id: number, value: unknown): Promise<void> {
  return post("/api/answer", id, value);
}

/** Ask the program to do something while the prompt stays open; results arrive as prompt updates. */
export function request(id: number, value: unknown): Promise<void> {
  return post("/api/request", id, value);
}

async function post(url: string, id: number, value: unknown): Promise<void> {
  await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ id, value }),
  });
}

/** POST /api/<name>/<action>. Throws an Error with the server's message if it refuses. */
export async function callApi<T = unknown>(name: string, action: string, body: unknown): Promise<T> {
  const res = await fetch(`/api/${name}/${action}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  const data = await res.json().catch(() => null);
  if (!res.ok) throw new Error(data?.error || `Greška ${res.status}`);
  return data as T;
}
