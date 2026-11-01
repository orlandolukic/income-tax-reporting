"""Jobs and the result of each job's last run, saved in data/jobs.json (git-ignored: jobs can hold
search values and results with company data). Every company has its own jobs: the file holds
{"companies": {key: {"label", "jobs", "runs"}}} and all functions here work on the company chosen with
set_company() (none chosen: no jobs, and saving is refused). Jobs saved before this (top-level "jobs" /
"runs") are moved to the first company opened.

A job: {"id", "name", "description", "tasks": [{"id", "type", "title", "params": {name: value},
"subtasks": [tasks run for each row of this task's result]}], "updated_at"}. A "Uslov" task also has
its branches: "then" (tasks run when it is met), "elifs" ([{"id", "params", "then"}], "inače ako") and
"else" (tasks run when none is met). A run: {"job_id", "status", "started_at", "finished_at", "tasks": [{"id", "type",
"title", "status", "value", "error", "started_at", "finished_at"}]}.
"""
import csv
import io
import json
import threading
import time
import uuid
from pathlib import Path

from tim_automation.jobs import secret_params

DATA_FILE = Path("data") / "jobs.json"
RESULTS_DIR = Path("data") / "results"
PREVIEW_ROWS = 25
STEP_RUNS_KEPT = 20  # reports ("Summary") kept per job
MAX_DEPTH = 20  # nesting of subtasks and condition branches (the page allows 6 subtask levels; branches add more)

_lock = threading.RLock()
_company: str | None = None  # key of the company whose jobs are shown and run


class NoCompany(Exception):
    """A job was to be saved while no company is open."""


def new_id() -> str:
    return uuid.uuid4().hex[:8]


def _read_file() -> dict:
    try:
        data = json.loads(DATA_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        data = {}
    return data if isinstance(data, dict) else {}


def set_company(key: str | None, label: str = "") -> None:
    """Show and run the jobs of this company from now on (None: no company is open)."""
    global _company
    with _lock:
        _company = key
        if key is None:
            return
        data = _read_file()
        companies = data.setdefault("companies", {})
        entry = companies.setdefault(key, {"jobs": [], "runs": {}})
        changed = entry.get("label") != label
        entry["label"] = label
        if "jobs" in data or "runs" in data:  # saved before jobs were kept per company
            entry["jobs"] = data.pop("jobs", []) + entry.get("jobs", [])
            entry["runs"] = {**data.pop("runs", {}), **entry.get("runs", {})}
            print(f"Jobs saved before they were kept per company now belong to {label or key}.")
            changed = True
        if changed:
            _write_file(data)


def company() -> str | None:
    return _company


def _read() -> dict:
    """The open company's jobs and runs (empty when no company is open)."""
    entry = _read_file().get("companies", {}).get(_company, {}) if _company else {}
    jobs = entry.get("jobs", [])
    for job in jobs:
        job["tasks"] = _migrate(job.get("tasks") or [])
    return {"jobs": jobs, "runs": entry.get("runs", {})}


def children(task: dict) -> list[dict]:
    """The tasks nested in `task`: its subtasks, then (for a "Uslov") its branches in order: AKO, each
    INAČE AKO, INAČE. Numbers on the page ("3.1", "3.2", ...) follow this order."""
    nested = list(task.get("subtasks") or [])
    nested += task.get("then") or []
    for branch in task.get("elifs") or []:
        nested += branch.get("then") or []
    nested += task.get("else") or []
    return nested


# Old "Uslov" settings: what to do when it is not met (before conditions had branches).
_OLD_SKIP, _OLD_JUMP, _OLD_STOP = "Preskoči ostatak", "Skoči na zadatak", "Prekini ceo posao"


def _migrate(tasks: list[dict]) -> list[dict]:
    """Turn old "Uslov" tasks (on_fail: skip the rest / jump / stop / note) into ones with branches: the
    tasks it skipped go into its AKO branch, "stop" becomes INAČE: "Prekini posao"."""
    out: list[dict] = []
    i = 0
    while i < len(tasks):
        task = dict(tasks[i])
        i += 1
        for key in ("subtasks", "then", "else"):
            if task.get(key):
                task[key] = _migrate(task[key])
        if task.get("elifs"):
            task["elifs"] = [{**b, "then": _migrate(b.get("then") or [])} for b in task["elifs"]]
        params = task.get("params") or {}
        if task.get("type") == "continue" and str(params.get("mode", "")).startswith("Izađi"):
            task = {**task, "type": "break", "params": {}}  # "Nastavi: izađi iz petlje" is now "Prekini"
        if task.get("type") == "condition" and "on_fail" in params:
            on_fail = str(params.get("on_fail") or _OLD_SKIP)
            target = params.get("target")
            task["params"] = {k: v for k, v in params.items() if k not in ("on_fail", "target")}
            if on_fail.startswith(_OLD_SKIP):
                task["then"], i = _migrate(tasks[i:]), len(tasks)
            elif on_fail.startswith(_OLD_JUMP):
                j = next((k for k in range(i, len(tasks)) if tasks[k].get("id") == target), i)
                task["then"], i = _migrate(tasks[i:j]), j
            elif on_fail.startswith(_OLD_STOP):
                task["else"] = [{"id": f"{task.get('id', '')}s", "type": "stop", "title": "", "params": {}}]
        out.append(task)
    return out


def _write(data: dict) -> None:
    """Save the open company's jobs and runs (the other companies' stay as they are)."""
    if not _company:
        raise NoCompany("Izaberite firmu: svaka firma ima svoje poslove.")
    whole = _read_file()
    entry = whole.setdefault("companies", {}).setdefault(_company, {})
    entry.update(jobs=data["jobs"], runs=data["runs"])
    _write_file(whole)


def _write_file(data: dict) -> None:
    DATA_FILE.parent.mkdir(exist_ok=True)
    DATA_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")


def snapshot() -> dict:
    with _lock:
        return _read()


def get_job(job_id: str) -> dict | None:
    with _lock:
        return next((j for j in _read()["jobs"] if j["id"] == job_id), None)


def save_job(job: dict) -> dict:
    """Create (no id) or replace a job. Returns the stored job."""
    def clean_task(task: dict, depth: int) -> dict:
        clean = {
            "id": task.get("id") or new_id(),
            "type": str(task.get("type", "")),
            "title": str(task.get("title", "")),
            # a newly typed secret (e.g. a PIN) goes to the credential store, the job keeps only its id
            "params": {str(k): secret_params.stash(v) for k, v in (task.get("params") or {}).items()},
        }
        if task.get("breaker"):  # "prekidač": see tasks.TaskType.breaker_when
            clean["breaker"] = True
        if depth < MAX_DEPTH and task.get("subtasks"):  # for each row of their task, or on a page it opened
            clean["subtasks"] = [clean_task(t, depth + 1) for t in task["subtasks"]]
        if task.get("type") == "condition" and depth < MAX_DEPTH:  # its branches
            clean["then"] = [clean_task(t, depth + 1) for t in task.get("then") or []]
            clean["elifs"] = [
                {"id": b.get("id") or new_id(), "params": {str(k): v for k, v in (b.get("params") or {}).items()},
                 "then": [clean_task(t, depth + 1) for t in b.get("then") or []]}
                for b in task.get("elifs") or []
            ]
            clean["else"] = [clean_task(t, depth + 1) for t in task.get("else") or []]
        return clean

    tasks = [clean_task(t, 0) for t in job.get("tasks", [])]
    clean = {
        "id": job.get("id") or new_id(),
        "name": str(job.get("name", "")).strip() or "Novi posao",
        "description": str(job.get("description", "")),
        "tasks": tasks,
        "updated_at": time.time(),
    }
    with _lock:
        data = _read()
        jobs = data["jobs"]
        index = next((i for i, j in enumerate(jobs) if j["id"] == clean["id"]), None)
        old = secret_params.ids(jobs[index]) if index is not None else set()
        if index is None:
            jobs.append(clean)
        else:
            jobs[index] = clean
        _write(data)
        secret_params.forget(old, _secrets_in_use())
    return clean


def _secrets_in_use() -> set[str]:
    """Secret ids used by any job of any company (in the file as written)."""
    try:
        return secret_params.ids(json.loads(DATA_FILE.read_text(encoding="utf-8")))
    except (OSError, ValueError):
        return set()


def delete_job(job_id: str) -> None:
    with _lock:
        data = _read()
        old = set().union(*(secret_params.ids(j) for j in data["jobs"] if j["id"] == job_id))
        data["jobs"] = [j for j in data["jobs"] if j["id"] != job_id]
        data["runs"].pop(job_id, None)
        _write(data)
        secret_params.forget(old, _secrets_in_use())
    for path in RESULTS_DIR.glob(f"{job_id}-*"):  # its results and reports
        path.unlink(missing_ok=True)


STEP_COLUMNS = ["Korak", "Vreme", "Trajanje (s)", "Broj", "Zadatak", "Vrsta", "Red", "Red (podaci)", "Status",
                "Rezultat", "Napomena", "Greška", "Ulaz", "Zapis"]


def _history_file(job_id: str) -> Path:
    return RESULTS_DIR / f"{job_id}-istorija.json"


def step_history(job_id: str) -> list[dict]:
    """The job's saved run reports, newest first: [{"fajl", "status", "started_at", "finished_at", "napomena",
    "koraci"}]."""
    try:
        return json.loads(_history_file(job_id).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []


def save_steps(job_id: str, job_name: str, run: dict, steps: list[dict]) -> str:
    """Save a run's report to data/results/<job>-koraci-<start>.json and .csv, keep the newest
    STEP_RUNS_KEPT. Returns the file name (without extension)."""
    name = f"{job_id}-koraci-{int(run.get('started_at') or time.time())}"
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    report = {"posao": job_name, "run": run, "koraci": steps}
    (RESULTS_DIR / f"{name}.json").write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    out = io.StringIO()
    writer = csv.writer(out, delimiter=";")
    writer.writerow(STEP_COLUMNS)
    for s in steps:
        writer.writerow([
            s["n"], time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(s["pocetak"])),
            str(s["trajanje"] if s["trajanje"] is not None else "").replace(".", ","), s["broj"], s["naziv"], s["vrsta"],
            s["red"], s["red_opis"], s["status"], s["rezultat"], s["napomena"], s["greska"],
            json.dumps(s["ulaz"], ensure_ascii=False) if s["ulaz"] is not None else "", s.get("zapis", "").strip(),
        ])
    (RESULTS_DIR / f"{name}.csv").write_text(out.getvalue(), encoding="utf-8-sig", newline="")
    with _lock:
        history = [h for h in step_history(job_id) if h.get("fajl") != name]
        failed = sum(s["status"] == "failed" for s in steps)
        history.insert(0, {**run, "fajl": name, "koraci": len(steps), "greske": failed})
        for old in history[STEP_RUNS_KEPT:]:
            for ext in (".json", ".csv"):
                (RESULTS_DIR / f"{old['fajl']}{ext}").unlink(missing_ok=True)
        _history_file(job_id).write_text(json.dumps(history[:STEP_RUNS_KEPT], ensure_ascii=False, indent=1),
                                         encoding="utf-8")
    return name


def load_steps(job_id: str, name: str = "") -> dict | None:
    """A saved report {"run", "koraci", "fajl"} (default: the newest), or None."""
    history = step_history(job_id)
    if not name:
        if not history:
            return None
        name = history[0]["fajl"]
    if not name.startswith(f"{job_id}-koraci-") or "/" in name or "\\" in name:
        return None
    try:
        report = json.loads((RESULTS_DIR / f"{name}.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return {"run": report.get("run"), "koraci": report.get("koraci", []), "fajl": name}


def save_run(run: dict) -> None:
    with _lock:
        data = _read()
        data["runs"][run["job_id"]] = run
        _write(data)


def preview(value, job_id: str, task_id: str):
    """For a result with rows: save all rows to data/results/<job>-<task>.json and .csv and return the
    value with only the first PREVIEW_ROWS rows, plus the file name ("fajl"). Other values unchanged."""
    if not (isinstance(value, dict) and isinstance(value.get("redovi"), list)):
        return value
    rows = value["redovi"]
    name = f"{job_id}-{task_id}"
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    (RESULTS_DIR / f"{name}.json").write_text(json.dumps(value, ensure_ascii=False, indent=1), encoding="utf-8")
    columns = value.get("kolone") or (list(rows[0]) if rows else [])
    out = io.StringIO()
    # Semicolons and a BOM so Excel with Serbian regional settings opens it correctly.
    writer = csv.DictWriter(out, columns, delimiter=";", extrasaction="ignore")
    writer.writeheader()
    writer.writerows(r for r in rows if isinstance(r, dict))
    (RESULTS_DIR / f"{name}.csv").write_text(out.getvalue(), encoding="utf-8-sig", newline="")
    return {**value, "redovi": rows[:PREVIEW_ROWS], "broj": len(rows), "fajl": name}
