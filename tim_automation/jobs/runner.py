"""Runs jobs: the page asks for a run (server thread), the main thread executes it task by task in the
TiM ERP browser (WebDriver must only be used from there) and every change is published to the page."""
import json
import queue
import threading
import time
import traceback

from tim_automation import log, ui
from tim_automation.jobs import conditions, pages, secret_params, store, templates
from tim_automation.pages import app_page, order_form, site_error
from tim_automation.jobs.tasks import (BUILTIN_CHOICES, EXIT_LOOP, JUMP_TO, TASK_TYPES, TaskCancelled, TaskContext,
                                       TaskType, describe)


class JobError(Exception):
    """A request the page made that can't be done (shown to the user)."""


class JobRunner:
    def __init__(self) -> None:
        self.driver = None
        self.status = ""  # e.g. company and year the browser is on; shown on the jobs page
        self.company_label = ""  # the company whose jobs are shown (each company has its own)
        self.queue: queue.Queue[str] = queue.Queue()
        self.current: dict | None = None  # the run in progress
        self.cancel_requested = threading.Event()
        self.stop_reason = ""  # set when a condition in a subtask stops the whole job
        self._active: dict | None = None  # result entry of the task being computed right now
        self._row_label = ""  # row label of the subtask being computed ("3/2"); its last part is $i$
        # Report of the run in progress ("Summary" on the job page): one step per task execution (each task,
        # once per row it runs for), with timing, input, result and the console lines printed meanwhile.
        self.steps: list[dict] = []
        self._contexts = 0  # "Uslov" steps of this run given a full context (CONTEXT_FULL)
        self._step: dict | None = None  # the step being executed
        self._run_thread: int | None = None
        # Set by main.py: restarts the browser, logs in again and opens the same company (then calls attach()).
        # Used when the site shows "Došlo je do nepredviđene greške"; the job then runs again from the start.
        self.recover = None
        self.site_error = False  # the site showed its error during the run in progress
        self.cancel_by_user = False
        log.subscribe(self._on_output)
        ui.register_api("jobs", self.handle_api)
        ui.register_files("results", store.RESULTS_DIR)
        self.publish()

    # --- state for the page ---------------------------------------------------------------------

    def publish(self) -> None:
        data = store.snapshot()
        if self.current:
            data["runs"][self.current["job_id"]] = self.current
        ui.set_shared("jobs", {
            **data,
            "company": {"key": store.company(), "label": self.company_label} if store.company() else None,
            "taskTypes": describe(),
            "choices": BUILTIN_CHOICES,
            "pages": pages.catalog(),
            "runner": {
                "ready": self.driver is not None,
                "status": self.status,
                "running": self.current["job_id"] if self.current else None,
                "queued": list(self.queue.queue),
            },
        })

    # --- requests from the page (server thread) -------------------------------------------------

    def handle_api(self, action: str, body: dict) -> dict | None:
        if action in ("save", "delete", "run") and body.get("company") != store.company():
            # The page still shows another company's jobs (the company was changed meanwhile).
            raise JobError("Firma je u međuvremenu promenjena: ovaj posao pripada drugoj firmi.")
        if action == "save":
            job = store.save_job(body["job"])
            self.publish()
            return {"job": job}
        if action == "delete":
            if self.current and self.current["job_id"] == body["id"]:
                raise JobError("Posao se upravo izvršava.")
            store.delete_job(body["id"])
            self.publish()
            return None
        if action == "run":
            if self.driver is None:
                raise JobError("Pretraživač još nije spreman: prijavite se i izaberite firmu.")
            if not store.get_job(body["id"]):
                raise JobError("Posao ne postoji.")
            if body["id"] in self.queue.queue or (self.current and self.current["job_id"] == body["id"]):
                raise JobError("Posao je već pokrenut.")
            self.queue.put(body["id"])
            self.publish()
            return None
        if action == "cancel":
            self.cancel_by_user = True
            self.cancel_requested.set()
            return None
        if action == "steps":
            return self._steps_for(body)
        if action == "history":
            return {"istorija": store.step_history(str(body.get("id", "")))}
        raise JobError(f"Nepoznata akcija: {action}")

    def _steps_for(self, body: dict) -> dict:
        """Steps of a run of job body["id"]: the one in progress (live, from step `od` on), or a saved one
        (body["fajl"], default the newest). Also the list of the job's saved runs."""
        job_id = str(body.get("id", ""))
        history = store.step_history(job_id)
        current = self.current
        if current and current["job_id"] == job_id and not body.get("fajl"):
            start = max(int(body.get("od") or 0), 0)
            for _ in range(5):  # the main thread may change a step while it is copied
                try:
                    steps = json.loads(json.dumps(self.steps[start:]))
                    break
                except (RuntimeError, TypeError, ValueError):
                    time.sleep(0.05)
            else:
                steps = []
            return {"istorija": history, "uzivo": True, "od": start, "run": _run_header(current), "koraci": steps}
        saved = store.load_steps(job_id, str(body.get("fajl") or ""))
        if saved is None:
            return {"istorija": history, "uzivo": False, "od": 0, "run": None, "koraci": []}
        return {"istorija": history, "uzivo": False, "od": 0, **saved}

    def _on_output(self, text: str) -> None:
        """Console output of the running job goes into the step being executed (its "zapis")."""
        step = self._step
        if step is None or threading.get_ident() != self._run_thread:
            return
        logged = step.get("zapis", "")
        if len(logged) < STEP_LOG_CHARS:
            step["zapis"] = (logged + text)[:STEP_LOG_CHARS]

    def _begin_step(self, task: dict, numbers: dict, label: str, row: dict | None) -> dict:
        task_type = TASK_TYPES.get(task["type"])
        type_title = task_type.title if task_type else task["type"]
        step = {
            "n": len(self.steps) + 1,
            "pocetak": time.time(),
            "trajanje": None,
            "id": task["id"],
            "broj": numbers.get(task["id"], "?"),
            "naziv": task.get("title") or type_title,
            "vrsta": type_title,
            "red": label,  # e.g. "3" or "3/2" (row 2 of the subtasks run for row 3)
            "red_opis": _row_text(row),
            "status": "running",
            "ulaz": None,  # params after references were resolved
            "rezultat": "",
            "detalji": None,
            "greska": "",
            "napomena": "",
            "zapis": "",
        }
        if len(self.steps) < MAX_STEPS:
            self.steps.append(step)
        if self.current is not None:
            self.current["koraci"] = step["n"]
        self._step = step
        return step

    def _end_step(self, step: dict, status: str, value=None, error: str = "") -> None:
        step.update(trajanje=round(time.time() - step["pocetak"], 3), status=status, greska=error)
        if value is not None:
            step.update(rezultat=_summary(value), detalji=_brief(value))
        if status == "failed":
            self._check_site_error()
        self._step = None

    def _activate(self, entry: dict, label: str) -> None:
        """Mark the task being computed now (shown highlighted on the job page and in the progress panel)."""
        if self._active is not None and self._active is not entry:
            self._active["aktivan"] = False
        entry["aktivan"] = True
        self._active = entry
        if self.current is not None:
            self.current["aktivno"] = {"id": entry["id"], "red": label}

    # --- running (main thread) ------------------------------------------------------------------

    def attach(self, driver, status: str = "", company: str | None = None) -> None:
        """Jobs of `company` (a key, see main.company_key) can run from now on, in this browser."""
        self.driver, self.status, self.company_label = driver, status, status
        store.set_company(company, status)
        self.publish()

    def detach(self) -> None:
        """No company is open any more: its jobs are hidden and the ones still waiting are dropped."""
        self.driver = None
        store.set_company(None)
        while not self.queue.empty():
            self.queue.get_nowait()
        self.publish()

    def process_pending(self) -> None:
        """Run the jobs the page asked for. Call this regularly from the main thread."""
        while self.driver is not None:
            try:
                job_id = self.queue.get_nowait()
            except queue.Empty:
                return
            job = store.get_job(job_id)
            if job:
                self.run(job)

    def run(self, job: dict) -> dict:
        """Run the job. If the site shows "Došlo je do nepredviđene greške", restart the browser (log in again,
        same company) and run the whole job again, up to SITE_ERROR_RETRIES times."""
        attempt = 1
        while True:
            run = self._run_once(job, attempt)
            if not self.site_error or self.cancel_by_user:
                return run
            if attempt > SITE_ERROR_RETRIES or self.recover is None:
                print(f"Site error: giving up after {attempt} attempts.")
                return run
            attempt += 1
            print(f"Site error ({site_error.MESSAGE}): restarting the browser and running "
                  f"{job['name']!r} again (attempt {attempt} of {SITE_ERROR_RETRIES + 1})...")
            ui.status("Greška sajta: ponovno pokretanje pretraživača i prijava...")
            try:
                self.recover()
            except Exception as e:
                traceback.print_exc()
                print(f"Could not restart the browser: {_message(e)}")
                run["napomena"] = f"{run.get('napomena', '')} Ponovno pokretanje pretraživača nije uspelo: {_message(e)}".strip()
                store.save_run(run)
                ui.status("Greška pri ponovnom pokretanju pretraživača")
                self.publish()
                return run
            job = store.get_job(job["id"]) or job

    def _check_site_error(self) -> None:
        """If the site shows its error message, end the run (it can't go on in this browser session)."""
        if self.site_error or not site_error.shown(self.driver):
            return
        self.site_error = True
        print(f"The site shows „{site_error.MESSAGE}“: stopping this run.")
        if self._step is not None:
            self._step["napomena"] = f"Sajt je prikazao „{site_error.MESSAGE}“."
        self.cancel_requested.set()

    def _run_once(self, job: dict, attempt: int) -> dict:
        self.cancel_requested.clear()
        self.cancel_by_user = False
        self.site_error = False
        run = {
            "job_id": job["id"],
            "status": "running",
            "started_at": time.time(),
            "finished_at": None,
            "tasks": [_result_entry(t) for t in job["tasks"]],
        }
        if attempt > 1:
            run["pokusaj"] = attempt
        self.current = run
        self.steps, self._step, self._run_thread, self._contexts = [], None, threading.get_ident(), 0
        run["koraci"] = 0
        ui.status(f"Posao: {job['name']}")
        print(f"Running job {job['name']!r} ({len(job['tasks'])} tasks)...")
        self.publish()
        ctx = TaskContext(self.driver, job, cancelled=self.cancel_requested.is_set)
        numbers = _numbers(job["tasks"])
        entries = _index(run["tasks"])
        self.stop_reason = ""
        try:
            outcome = self._run_list(ctx, job["tasks"], numbers, entries)
            if outcome.startswith(JUMP):  # the UI only offers later tasks, so this means the job changed
                outcome = "failed"
                run["napomena"] = "Zadatak na koji „Nastavi“ skače nije među sledećim zadacima."
            run["status"] = outcome or "done"
            if outcome == "stopped":
                run["napomena"] = self.stop_reason
            if self.site_error:
                run["status"] = "failed"
                retry = attempt <= SITE_ERROR_RETRIES and self.recover is not None and not self.cancel_by_user
                run["napomena"] = (f"Sajt je prikazao „{site_error.MESSAGE}“. "
                                   + ("Pretraživač se ponovo pokreće i posao se izvršava ispočetka."
                                      if retry else "Posao je zaustavljen."))
            if attempt > 1:
                run["napomena"] = f"Ponovni pokušaj {attempt - 1} (posle greške sajta). {run.get('napomena', '')}".strip()
            for r in _walk(run["tasks"]):
                if r["status"] in ("pending", "running"):
                    r["status"] = "skipped"
        finally:
            run["finished_at"] = time.time()
            run.pop("aktivno", None)
            for r in _walk(run["tasks"]):
                r.pop("aktivan", None)
                r.pop("red_napredak", None)
            self._active = None
            self._step = None
            try:
                run["koraci_fajl"] = store.save_steps(job["id"], job["name"], _run_header(run), self.steps)
            except OSError as e:
                print(f"Could not save the job report: {e}")
            self.current = None
            store.save_run(run)
            print(f"Job {job['name']!r}: {run['status']}")
            ui.status("Spremno")
            self.publish()
        return run

    def _run_list(self, ctx: TaskContext, tasks: list[dict], numbers: dict, entries: dict) -> str:
        """Run top-level tasks (or the branch of a top-level "Uslov") in order. Returns "" when all ran,
        else why it ended: "failed", "stopped", "cancelled" or a jump to a task that is not in `tasks`."""
        k = 0
        while k < len(tasks):
            task = tasks[k]
            k += 1
            if self.cancel_requested.is_set():
                return "cancelled"
            outcome = self._run_task(ctx, task, entries[task["id"]], numbers, entries)
            j = _jump_index(tasks, k, outcome)
            if j is not None:
                k = j
                continue
            if outcome:
                return outcome
        return "cancelled" if self.cancel_requested.is_set() else ""

    def _compute(self, ctx: TaskContext, task: dict, outputs: dict, numbers: dict, row: dict | None):
        """Run one task (once, or once per row for "svaki red") and return its JSON value."""
        task_type = TASK_TYPES.get(task["type"])
        if task_type is None:
            raise JobError(f"Nepoznata vrsta zadatka: {task['type']}")
        if task["type"] in LOOP_CONTROL and row is None and not _continue_signal(task).startswith(JUMP):
            raise JobError("„Nastavi“ (sledeći red) i „Prekini“ rade samo u petlji (podzadaci koji se izvršavaju za "
                           "svaki red, npr. u „Petlji“ ili pod „Pretragom“); ovde „Nastavi“ može samo da skoči na zadatak.")
        if task["type"] == "condition":
            return _jsonable(self._evaluate(ctx, task, task_type, outputs, numbers, row))
        params = dict(task.get("params") or {})
        secrets = {p.name: p.label for p in task_type.params if p.kind == "secret"}
        for name, label in secrets.items():  # from the credential store; never shown in the steps or results
            if secret_params.is_secret(params.get(name)):
                params[name] = secret_params.reveal(params[name], label)
        runs = resolve_params(task_type, params, outputs, numbers, row, _pass(self._row_label))
        if self._step is not None:
            shown = {**runs[0], **{n: secret_params.MASK for n in secrets if runs[0].get(n)}}
            self._step["ulaz"] = _brief(shown) if len(runs) == 1 else {"pokretanja": len(runs), "prvo": _brief(shown)}
        if len(runs) == 1:
            value = task_type.run(ctx, runs[0])
        else:  # "svaki red": once per row of the earlier task's result
            print(f"    Running once per row: {len(runs)} times")
            value = _merge([task_type.run(ctx, params) for params in runs])
        return _jsonable(value)

    def _evaluate(self, ctx, task: dict, task_type: TaskType, outputs: dict, numbers: dict, row: dict | None) -> dict:
        """Check a "Uslov": its own checks (AKO), then each INAČE AKO until one is met. The value says which
        branch runs ("grana": "then", an INAČE AKO id or "else") and lists the checks that were made."""
        branches = [("AKO", task.get("params") or {}, "then")]
        branches += [(f"INAČE AKO {n}", b.get("params") or {}, b["id"]) for n, b in enumerate(task.get("elifs") or [], 1)]
        checked = []
        chosen, name = "else", "INAČE"
        first = None
        names = _task_names(ctx.job)
        if self._step is not None:  # what the checks could see: earlier tasks, the current row, the loops
            self._step["kontekst"] = self._context(task, outputs, numbers, names, row)
        for label, params, key in branches:
            value = task_type.run(ctx, resolve_params(task_type, params, outputs, numbers, row, _pass(self._row_label))[0])
            first = value if first is None else first
            raw = [c for c in (params.get("checks") or []) if c.get("operator")]
            for i, r in enumerate(value["redovi"]):
                check = raw[i] if i < len(raw) else {}
                desno = _source_text(check.get("vrednost"), numbers, names)
                if check.get("operator") == "Između":
                    desno += f" i {_source_text(check.get('do'), numbers, names)}"
                no_value = check.get("operator") in (conditions.EMPTY, conditions.NOT_EMPTY)
                checked.append({"Grana": label, **r, "Levo iz": _source_text(check.get("levo"), numbers, names),
                                "Desno iz": "" if no_value else desno})
            if value["uslov"]:
                chosen, name = key, label
                break
        ctx.log(f"Branch: {name}")
        return {
            "uslov": first["uslov"],  # whether AKO itself is met
            "ispunjen": first["ispunjen"],
            "grana": chosen,
            "grana_naziv": name,
            "kolone": ["Grana", "Provera", "Ispunjeno", "Leva vrednost", "Levo iz", "Operator", "Desna vrednost",
                       "Desno iz", "Poređenje", "Objašnjenje"],
            "redovi": checked,
            "broj": len(checked),
        }

    def _context(self, task: dict, outputs: dict, numbers: dict, names: dict, row: dict | None) -> dict:
        """For the run report of a "Uslov": every task that ran before it (its last step: status, row, result, error,
        and the value a check here would get), the row it runs for and the row each enclosing loop is at."""
        full = self._contexts < CONTEXT_FULL
        self._contexts += 1
        latest: dict[str, dict] = {}
        for step in self.steps:
            if step is not self._step and step["id"] != task["id"]:
                latest.pop(step["id"], None)
                latest[step["id"]] = step  # the newest step of each task, in the order they last ran
        tasks = []
        for tid, step in latest.items():
            item = {k: step.get(k) for k in ("broj", "naziv", "vrsta", "status", "red", "red_opis", "rezultat", "greska",
                                              "napomena")}
            if full and tid in outputs:
                item["vrednost"] = _brief(outputs[tid], rows=CONTEXT_ROWS)
            tasks.append(item)
        loops = []
        for tid, here in (outputs.get(templates.LOOPS) or {}).items():
            loops.append({"broj": numbers.get(tid, "?"), "naziv": names.get(tid, tid), "prolaz": here.get("prolaz"),
                          "red": _brief(here.get("red"))})
        return {"zadaci": tasks, "trenutni_red": _brief(row) if row else None, "petlje": loops, "skraceno": not full}

    def _run_task(self, ctx: TaskContext, task: dict, result: dict, numbers: dict, entries: dict) -> str:
        """Run a top-level task (with its subtasks / branch). Returns "" to go on, or why the job ends."""
        task_type = TASK_TYPES.get(task["type"])
        result.update(status="running", started_at=time.time())
        self._activate(result, "")
        self.publish()
        name = task.get("title") or (task_type.title if task_type else task["type"])
        print(f"  Task {name!r}...")

        def progress(text: str) -> None:
            result["progress"] = text
            self.publish()

        ctx.progress = progress
        value = None
        step = self._begin_step(task, numbers, "", None)
        self._row_label = ""
        try:
            value = self._compute(ctx, task, ctx.outputs, numbers, None)
            # Later tasks get every row; the page gets a preview and links to the full result.
            ctx.outputs[task["id"]] = value
            result.update(status="done", value=store.preview(value, ctx.job["id"], task["id"]))
            self._end_step(step, "done", value)
        except NotImplementedError:
            result.update(status="not_implemented")
            self._end_step(step, "not_implemented")
        except TaskCancelled as e:  # "Zaustavi" while the task was waiting
            print(f"  Task {name!r}: stopped by the user")
            result.update(status="cancelled", error=str(e))
            self._end_step(step, "cancelled", error=str(e))
        except Exception as e:
            traceback.print_exc()
            result.update(status="failed", error=_message(e))
            self._end_step(step, "failed", error=_message(e))
        result["finished_at"] = time.time()
        result["progress"] = ""
        self._check_site_error()
        print(f"  Task {name!r}: {result['status']}")
        self.publish()
        down = ""
        if result["status"] == "done" and not _breaks(task, value):
            acc: dict = {}
            down = self._descend(ctx, task, value, dict(ctx.outputs), numbers, None, "", acc, entries)
            self._finish(ctx, task.get("subtasks") or [], acc, numbers, entries)
        if any(r["status"] == "failed" for r in _walk([result])):
            return "failed"
        if self.stop_reason:  # a "Prekini posao" in a subtask
            return "stopped"
        if self.cancel_requested.is_set():
            return "cancelled"
        if result["status"] != "done":
            return ""
        if _breaks(task, value):
            result["napomena"] = "Uslov nije ispunjen, pa je posao prekinut (sledeći zadaci se ne izvršavaju)."
            step["napomena"] = "Prekidač: uslov nije ispunjen, posao je prekinut."
            self.stop_reason = f"Prekidač u zadatku #{numbers[task['id']]}: uslov nije ispunjen."
            print("  Condition not met: job stopped.")
            return "stopped"
        if task["type"] == STOP:
            result["napomena"] = "Posao je prekinut ovde."
            step["napomena"] = "Posao je prekinut."
            self.stop_reason = f"Posao je prekinut zadatkom #{numbers[task['id']]} („Prekini posao“)."
            print("  Job stopped.")
            return "stopped"
        if task["type"] == "condition":
            result["grane"] = {value["grana"]: 1}
            step["napomena"] = f"Grana: {value.get('grana_naziv', value['grana'])}"
            return self._run_list(ctx, branch_tasks(task, value["grana"]), numbers, entries)
        if task["type"] == CONTINUE:  # at the top level it can only jump
            result["napomena"] = f"Skok na zadatak #{numbers.get(_target(task), '?')}."
            step["napomena"] = result["napomena"]
            return _continue_signal(task)
        return down  # a jump from the subtasks of a page it opened

    def _descend(self, ctx, task: dict, value, outputs: dict, numbers: dict, row: dict | None, label: str,
                 acc: dict, entries: dict) -> str:
        """After `task` ran: run its subtasks (for each row of its result, or once on the page it opened),
        then go back to the page it came from if it opened another one. Returns what a "Nastavi" in
        subtasks that ran once asks of an outer list ("continue", "exit", a jump; see _run_group), else ""."""
        try:
            mode = _children_mode(task)
            subtasks = task.get("subtasks") or []
            if mode == "rows":
                rows = value.get("redovi") if isinstance(value, dict) else None
                if rows is None:
                    for sub in subtasks:
                        _collector(acc, sub)["errors"].append(f"zadatak #{numbers[task['id']]} ne vraća redove")
                    return ""
                print(f"    Subtasks for {len(rows)} rows...")
                for sub in subtasks:
                    _collector(acc, sub)["rows"] += len(rows)
                # The loops this one is in, and the data set a "Petlja" goes through (its row i = the loop's row i).
                outer = outputs.get(templates.LOOPS) or {}
                izvor = (task.get("params") or {}).get("izvor") if task["type"] == "loop" else None
                source_id = izvor.get("ref") if isinstance(izvor, dict) else None
                for i, r in enumerate(rows):
                    if self.cancel_requested.is_set() or self.stop_reason:
                        break
                    entries[task["id"]]["progress"] = f"Podzadaci: red {i + 1} / {len(rows)}"
                    entries[task["id"]]["red_napredak"] = [i + 1, len(rows)]
                    self.publish()
                    row_label = f"{label}/{i + 1}" if label else str(i + 1)
                    # An error, a breaker or "Nastavi" ends this row's subtasks; the next row goes on,
                    # unless "Nastavi" leaves the loop.
                    here = {"red": r, "prolaz": i + 1}
                    local = dict(outputs)
                    local[templates.LOOPS] = {**outer, **({source_id: here} if source_id else {}), task["id"]: here}
                    outcome = self._run_group(ctx, subtasks, local, numbers, r, row_label, acc, entries)
                    if outcome == "exit":
                        entries[task["id"]]["napomena"] = (f"Petlja je prekinuta u redu {row_label} („Nastavi“: izađi "
                                                           f"iz petlje); ostali redovi nisu obrađeni.")
                        print(f"    Row {row_label}: leaving the loop of #{numbers[task['id']]}.")
                        break
                    if outcome.startswith(JUMP):
                        print(f"    Row {row_label}: jump target not found in this row; next row.")
                entries[task["id"]]["progress"] = ""
                entries[task["id"]].pop("red_napredak", None)
            elif mode == "once":
                for sub in subtasks:
                    _collector(acc, sub)["rows"] += 1
                local = dict(outputs)
                local[task["id"]] = value
                outcome = self._run_group(ctx, subtasks, local, numbers, row, label or "1", acc, entries)
                if outcome in ("continue", "exit") or outcome.startswith(JUMP):
                    return outcome
        finally:
            back = value.get("prikaz_pre") if isinstance(value, dict) else None
            if back:  # the task opened another page: make sure we are back where it started
                app_page.return_to(ctx.driver, back)
        return ""

    def _run_group(self, ctx, subtasks: list[dict], outputs: dict, numbers: dict, row: dict | None, label: str,
                   acc: dict, entries: dict) -> str:
        """Run sibling subtasks in order for one row (or once); a "Uslov" runs the tasks of the branch it
        chose in the same row, as if they were in this list. Returns "" when the group finished, "break"
        when an error or a breaker ended it, or what a "Nastavi" asks: "continue" (next row), "exit" (leave
        the row loop) or "jump:<task id>" (go on from that task; handled by the list that has it)."""
        k = 0
        while k < len(subtasks):
            sub = subtasks[k]
            k += 1
            if self.cancel_requested.is_set() or self.stop_reason:
                return ""
            entry = entries[sub["id"]]
            if entry["status"] == "pending":
                entry.update(status="running", started_at=time.time())
            coll = _collector(acc, sub)

            def progress(text: str, entry=entry) -> None:
                entry["progress"] = f"Red {label}: {text}"
                self.publish()

            ctx.progress = progress
            entry["progress"] = f"Red {label}"
            self._activate(entry, label)
            self.publish()
            number = numbers[sub["id"]]
            step = self._begin_step(sub, numbers, label, row)
            self._row_label = label
            try:
                out = self._compute(ctx, sub, outputs, numbers, row)
                self._end_step(step, "done", out)
            except NotImplementedError:
                coll["not_implemented"] = True
                self._end_step(step, "not_implemented")
                continue
            except TaskCancelled as e:
                self._end_step(step, "cancelled", error=str(e))
                print(f"    Row {label}: subtask #{number} stopped by the user")
                return "break"
            except Exception as e:
                traceback.print_exc()
                self._end_step(step, "failed", error=_message(e))
                coll["errors"].append(f"red {label}: {_message(e)}")
                print(f"    Row {label}: subtask #{number} failed: {_message(e)}")
                return "break"  # the following subtasks of this row may need this one's result
            outputs[sub["id"]] = out
            coll["values"].append(out)
            signal = ""
            if sub["type"] in LOOP_CONTROL:
                coll["broken"].append(label)
                signal = _continue_signal(sub)
                step["napomena"] = {"continue": "Nastavi: sledeći red.", "exit": "Prekini: izlaz iz petlje."}.get(
                    signal, f"Nastavi: skok na zadatak #{numbers.get(_target(sub), '?')}.")
                print(f"    Row {label}: #{number} {'Prekini' if sub['type'] == BREAK else 'Nastavi'} -> {signal}")
            if sub["type"] == STOP:
                coll["broken"].append(label)
                self.stop_reason = f"Posao je prekinut zadatkom #{number} („Prekini posao“, red {label})."
                step["napomena"] = "Posao je prekinut."
                print(f"    Row {label}: #{number} stopped the job.")
                return ""
            if sub["type"] == "condition":
                key = out["grana"]
                step["napomena"] = f"Grana: {out.get('grana_naziv', key)}"
                coll["grane"][key] = coll["grane"].get(key, 0) + 1
                branch = branch_tasks(sub, key)
                for t in branch:
                    _collector(acc, t)["rows"] += 1
                signal = self._run_group(ctx, branch, outputs, numbers, row, label, acc, entries)
            elif sub["type"] not in LOOP_CONTROL:
                if _breaks(sub, out):
                    step["napomena"] = "Prekidač: uslov nije ispunjen, ostali podzadaci ovog reda su preskočeni."
                    coll["broken"].append(label)
                    print(f"    Row {label}: breaker #{number}: condition not met, rest of the row skipped.")
                    return "break"
                signal = self._descend(ctx, sub, out, outputs, numbers, row, label, acc, entries)
            j = _jump_index(subtasks, k, signal)
            if j is not None:  # "Nastavi" jumps to a later task of this list
                k = j
                continue
            if signal:
                return signal
        return ""

    def _finish(self, ctx, subtasks: list[dict], acc: dict, numbers: dict, entries: dict) -> None:
        """Join each subtask's results from all its runs into one value and set its status (recursively)."""
        for sub in subtasks:
            entry = entries[sub["id"]]
            coll = acc.get(sub["id"])
            # Never started (e.g. after a "Nastavi" or in a branch that was not taken).
            if coll is None or (entry["status"] == "pending" and coll["rows"] and not coll["errors"]):
                entry.update(status="skipped", progress="")
            else:
                found = [v for v in coll["values"] if v is not None]
                merged = _merge(found) if found or coll["rows"] == 0 else None
                if merged is not None:
                    ctx.outputs[sub["id"]] = merged
                failed = coll["errors"]
                if coll["broken"]:
                    n = len(coll["broken"])
                    shown = ", ".join(coll["broken"][:20]) + ("…" if n > 20 else "")
                    signal = _continue_signal(sub) if sub["type"] in LOOP_CONTROL else ""
                    if signal == "continue":
                        entry["napomena"] = f"Prelazak na sledeći red u {n} {_rows_word(n)} ({shown})."
                    elif signal == "exit":
                        entry["napomena"] = f"Izlaz iz petlje (red {shown})."
                    elif signal:
                        entry["napomena"] = (f"Skok na zadatak #{numbers.get(_target(sub), '?')} u {n} {_rows_word(n)} "
                                             f"({shown}).")
                    elif sub["type"] == STOP:
                        entry["napomena"] = f"Posao je prekinut (red {shown})."
                    else:
                        entry["napomena"] = (f"Uslov nije ispunjen u {n} od {coll['rows']} redova ({shown}); "
                                             f"za njih su ostali podzadaci preskočeni.")
                if coll["grane"]:
                    entry["grane"] = coll["grane"]
                entry.update(
                    status="failed" if failed else "not_implemented" if coll["not_implemented"] else "done",
                    value=store.preview(merged, ctx.job["id"], sub["id"]) if merged is not None else None,
                    error=(f"{len(failed)} od {coll['rows']} redova sa greškom. Prva: {failed[0]}" if failed else ""),
                    errors=failed,
                    progress="",
                    finished_at=time.time(),
                )
            self._finish(ctx, store.children(sub), acc, numbers, entries)
        self.publish()


def _children_mode(task: dict) -> str | None:
    """How a task's subtasks run: "rows" (for each row of its result), "once" (after it, e.g. on the
    page it opened) or None (it has none, or they are switched off)."""
    task_type = TASK_TYPES.get(task["type"])
    if not task.get("subtasks") or task_type is None:
        return None
    if task_type.subtasks_when:
        name, wanted = task_type.subtasks_when
        return "once" if (task.get("params") or {}).get(name) == wanted else None
    if task_type.subtasks_once:
        return "once"
    return "rows" if task_type.returns_rows else None


SITE_ERROR_RETRIES = 2  # runs of a job again after "Došlo je do nepredviđene greške" (each in a new browser)
STEP_LOG_CHARS = 4000  # console text kept per step
CONTEXT_ROWS = 5  # rows of each earlier task's value in a "Uslov" step's context
CONTEXT_FULL = 300  # "Uslov" steps per run given the earlier values (later ones: the list of tasks only)
BRIEF_ROWS = 25  # rows of a value kept in a step
MAX_STEPS = 50000  # steps kept per run
ROW_KEYS = ("Dokument", "Broj računa", "Broj naloga", "R.b.", "Konto", "Komitent", "Naziv")
SKIP_KEYS = {"kolone", "redovi", "broj", "fajl", "prikaz_pre", "po_pokretanju", "ukupno"}


def _run_header(run: dict) -> dict:
    return {k: run.get(k) for k in ("status", "started_at", "finished_at", "napomena")}


def _row_text(row: dict | None) -> str:
    """A few cells that tell which row a step ran for (e.g. its document number)."""
    if not row:
        return ""
    picked = [f"{k}: {row[k]}" for k in ROW_KEYS if str(row.get(k) or "").strip()][:2]
    if not picked:
        picked = [str(v) for v in row.values() if str(v or "").strip()][:3]
    return " · ".join(picked)[:120]


def _short(value, limit: int = 60) -> str:
    text = str(value)
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _summary(value) -> str:
    """One line about a task's value for the report: the chosen branch and checks, number of rows and
    totals, or its main fields."""
    if isinstance(value, dict):
        if "grana_naziv" in value:  # a "Uslov" (the chosen branch is the step's "napomena"): its checks
            checks = [f"{r.get('Grana', '')}: {r.get('Provera', '')} → {r.get('Ispunjeno', '')}" for r in value.get("redovi") or []]
            return _short("; ".join(checks) or value["grana_naziv"], 400)
        parts = []
        if isinstance(value.get("redovi"), list):
            parts.append(f"{value.get('broj', len(value['redovi']))} redova")
        if isinstance(value.get("ukupno"), dict):
            parts += [f"{k}: {_short(v, 30)}" for k, v in list(value["ukupno"].items())[:6]]
        parts += [f"{k}: {_short(v)}" for k, v in value.items()
                  if k not in SKIP_KEYS and not isinstance(v, (dict, list))][:8]
        parts += [f"{k}: {len(v)} stavki" for k, v in value.items() if k not in SKIP_KEYS and isinstance(v, list)][:3]
        return _short(" · ".join(parts), 400)
    if isinstance(value, list):
        return f"{len(value)} stavki"
    return _short(value, 400)


def _brief(value, depth: int = 0, rows: int = BRIEF_ROWS):
    """A smaller JSON copy of a value for the report: first rows of a table, shortened texts."""
    if depth > 5:
        return "…"
    if isinstance(value, dict):
        out = {}
        for k, v in value.items():
            if k == "redovi" and isinstance(v, list) and len(v) > rows:  # as many as the job page shows
                out[k] = [_brief(r, depth + 1, rows) for r in v[:rows]]
                out.setdefault("broj", len(v))
            elif k == "po_pokretanju" and rows < BRIEF_ROWS:  # a context needs no per-run details
                continue
            else:
                out[str(k)] = _brief(v, depth + 1, rows)
        return out
    if isinstance(value, (list, tuple)):
        items = [_brief(v, depth + 1, rows) for v in list(value)[:10]]
        return items + [f"… još {len(value) - 10}"] if len(value) > 10 else items
    if isinstance(value, str):
        return _short(value, 500)
    if value is None or isinstance(value, (bool, int, float)):
        return value
    return _short(repr(value), 200)


CONTINUE, BREAK, STOP = "continue", "break", "stop"  # "Nastavi", "Prekini" and "Prekini posao" (see tasks.py)
LOOP_CONTROL = (CONTINUE, BREAK)
JUMP = "jump:"


def _target(task: dict) -> str:
    return str((task.get("params") or {}).get("target") or "")


def _continue_signal(task: dict) -> str:
    """What a "Nastavi" / "Prekini" asks: "continue" (next row), "exit" (leave the row loop) or "jump:<task id>"."""
    if task.get("type") == BREAK:
        return "exit"
    mode = (task.get("params") or {}).get("mode")
    if mode == EXIT_LOOP:
        return "exit"
    if mode == JUMP_TO:
        return f"{JUMP}{_target(task)}"
    return "continue"


def _jump_index(tasks: list[dict], start: int, signal: str) -> int | None:
    """Index of the jump target in tasks[start:], or None (not a jump, or the target is elsewhere)."""
    if not signal.startswith(JUMP):
        return None
    target = signal[len(JUMP):]
    return next((j for j in range(start, len(tasks)) if tasks[j]["id"] == target), None)


def branch_tasks(task: dict, key: str) -> list[dict]:
    """The tasks of a "Uslov" branch: "then", "else" or the id of one of its INAČE AKO branches."""
    if key in ("then", "else"):
        return task.get(key) or []
    return next((b.get("then") or [] for b in task.get("elifs") or [] if b["id"] == key), [])


def _collector(acc: dict, task: dict) -> dict:
    return acc.setdefault(task["id"], {"values": [], "errors": [], "broken": [], "grane": {},
                                       "not_implemented": False, "rows": 0})


def _result_entry(task: dict) -> dict:
    entry = {"id": task["id"], "type": task["type"], "title": task.get("title", ""), "status": "pending",
             "value": None, "error": "", "progress": "", "started_at": None, "finished_at": None}
    nested = store.children(task)
    if nested:  # subtasks and the tasks of a condition's branches
        entry["subtasks"] = [_result_entry(t) for t in nested]
    return entry


def _walk(entries: list[dict]):
    for entry in entries:
        yield entry
        yield from _walk(entry.get("subtasks", []))


def _index(entries: list[dict]) -> dict[str, dict]:
    return {entry["id"]: entry for entry in _walk(entries)}


def _numbers(tasks: list[dict], prefix: str = "") -> dict[str, str]:
    """Task id -> its number as shown on the page: "2", "2.1" (first subtask of 2), "2.1.1", ..."""
    numbers = {}
    for i, task in enumerate(tasks, 1):
        number = f"{prefix}{i}"
        numbers[task["id"]] = number
        numbers.update(_numbers(store.children(task), number + "."))
    return numbers


def _breaks(task: dict, value) -> bool:
    """A breaker ("prekidač") task whose condition is not met: a subtask skips the rest of its row, a
    top-level task stops the job."""
    return bool(task.get("breaker")) and isinstance(value, dict) and value.get("uslov") is False


def _rows_word(n: int) -> str:
    """ "red" / "reda" / "redova" after the number n."""
    if n % 10 == 1 and n % 100 != 11:
        return "red"
    return "reda" if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14 else "redova"


def _message(e: Exception) -> str:
    return f"{type(e).__name__}: {e}".splitlines()[0]


PARENT_ROW = "@red"  # reference to the row a subtask is running for


def _origin(value, numbers: dict) -> str:
    """Where a param's value comes from, for messages: "iz zadatka #2.1, kolona „Dokument“", a token, or typed."""
    if isinstance(value, dict) and value.get("ref"):
        source = value["ref"]
        where = "trenutnog reda" if source == PARENT_ROW else f"zadatka #{numbers.get(source, '?')}"
        column = value.get("column")
        return f"iz {where}" + (f", kolona „{column}“" if column else "")
    if templates.has_tokens(value):
        return f"iz „{value}“"
    return "upisano"


PICK_WORDS = {"first": "prvi red", "all": "svi redovi", "count": "broj redova", "total": "ukupno", "value": "cela vrednost",
              "current": "trenutni red petlje"}


def _task_names(job: dict) -> dict[str, str]:
    """Task id -> the name shown on the page (its title, else its type's)."""
    names = {}

    def walk(tasks: list[dict]) -> None:
        for t in tasks:
            kind = TASK_TYPES.get(t.get("type"))
            names[t["id"]] = t.get("title") or (kind.title if kind else t.get("type", ""))
            walk(store.children(t))

    walk(job.get("tasks") or [])
    return names


def _source_text(value, numbers: dict, names: dict) -> str:
    """Where a check's value comes from, for the run report: "#2 „Pretraga“ · prvi red · kolona „Dokument“", a value
    with tokens, or "upisano"."""
    if isinstance(value, dict) and value.get("ref"):
        source = value["ref"]
        if source == PARENT_ROW:
            where = "trenutni red"
        else:
            where = f"#{numbers.get(source, '?')} „{names.get(source, source)}“"
            pick = value.get("pick", "first")
            where += f" · {value.get('row') or 1}. red" if pick == "row" else f" · {PICK_WORDS.get(pick, pick)}"
        column = value.get("column")
        return where + (f" · kolona „{column}“" if column else "")
    if isinstance(value, list):
        return f"lista od {len(value)}: " + ", ".join(_source_text(v, numbers, names) for v in value[:3])
    if templates.has_tokens(value):
        return f"vrednost „{value}“"
    return "upisano" if value not in ("", None) else ""


def _check_kind(spec, value, origin: str) -> None:
    """A number or date field must get a number or date (e.g. not a document number from another data set)."""
    if spec.kind not in ("number", "date") or value in ("", None) or isinstance(value, (dict, list)):
        return
    if spec.kind == "number":
        text = str(value).strip().lstrip("+-").strip() if not isinstance(value, (int, float)) else value
        if isinstance(value, bool) or conditions.number(text) is None:
            raise JobError(f"Polje „{spec.label}“ očekuje broj, a dobilo je „{value}“ ({origin}).")
    else:
        try:
            order_form.normalize_date(value)
        except ValueError:
            raise JobError(f"Polje „{spec.label}“ očekuje datum (DD/MM/GGGG), a dobilo je „{value}“ ({origin}).") from None


def _pass(label: str) -> int | None:
    """The current pass of the innermost loop ($i$) from a row label like "3/2"."""
    try:
        return int(label.split("/")[-1]) if label else None
    except ValueError:
        return None


def resolve_params(task_type: TaskType, params: dict, outputs: dict, numbers: dict,
                   row: dict | None = None, index: int | None = None) -> list[dict]:
    """The task's params with values taken from earlier tasks filled in, plus defaults. A reference
    is {"ref": task id, "pick": ..., "column": ..., "row": ...}; pick is "first" (first row), "row"
    (row number `row`, from 1), "all" (every row: the task runs once per row), "count" (number of
    rows), "total" (`column` of the result's totals) or "value" (the whole value). In a subtask,
    {"ref": "@red", "pick": "current", "column": ...} is a column of the row it runs for, and an empty
    param with `row_column` takes that column of the row. Text may hold tokens like "$2.1[i].Dokument$" (see
    templates.py), filled in here. Returns one param set per run."""
    fixed: dict = {}
    each: tuple[str, list] | None = None
    def shown(spec) -> bool:
        if not spec.show_if:
            return True
        name, wanted = spec.show_if
        other = next((p for p in task_type.params if p.name == name), None)
        return (params.get(name) or (other.default if other else "")) == wanted

    for spec in task_type.params:
        value = params.get(spec.name, "")
        origin = _origin(value, numbers)
        if isinstance(value, list):  # e.g. filters: references inside are resolved one by one
            value = _resolve_nested(value, outputs, numbers, row, index)
        if templates.has_tokens(value):
            value = templates.render(value, outputs, numbers, row, index)
        if isinstance(value, dict) and value.get("ref"):
            value = _pick(value, outputs, numbers, row)
            if isinstance(value, _Each):
                if each:
                    raise JobError("Samo jedno polje može da koristi „svaki red“.")
                for v in value.values:
                    _check_kind(spec, v, origin)
                each = (spec.name, value.values)
                continue
        _check_kind(spec, value, origin)
        if value in ("", None) and row is not None and spec.row_column:
            value = row.get(spec.row_column, "")
        if value in ("", None):
            value = spec.default
        if spec.required and value in ("", None) and shown(spec):
            raise JobError(f"Polje „{spec.label}“ je obavezno.")
        fixed[spec.name] = value
    if each is None:
        return [fixed]
    name, values = each
    return [{**fixed, name: v} for v in values]


def _resolve_nested(value, outputs: dict, numbers: dict, row: dict | None, index: int | None = None):
    if isinstance(value, dict) and value.get("ref"):
        picked = _pick(value, outputs, numbers, row)
        # "Svaki red" inside filters/conditions = the list of values (a condition holds for any of them).
        return list(picked.values) if isinstance(picked, _Each) else picked
    if isinstance(value, dict):
        return {k: _resolve_nested(v, outputs, numbers, row, index) for k, v in value.items()}
    if isinstance(value, list):
        return [_resolve_nested(v, outputs, numbers, row, index) for v in value]
    if templates.has_tokens(value):
        return templates.render(value, outputs, numbers, row, index)
    return value


class _Each:
    def __init__(self, values: list):
        self.values = values


def _pick(ref: dict, outputs: dict, numbers: dict, row: dict | None = None):
    source = ref["ref"]
    column = ref.get("column", "")
    if source == PARENT_ROW:
        if row is None:
            raise JobError("„Trenutni red“ postoji samo u podzadacima.")
        if column not in row:
            raise JobError(f"Kolona „{column}“ ne postoji u trenutnom redu. Kolone: {', '.join(row)}.")
        return row[column]
    label = f"zadatak #{numbers.get(source, '?')}"
    if source not in numbers:
        raise JobError("Polje koristi zadatak koji više ne postoji u ovom poslu.")
    if ref.get("pick") == "current":  # the row an enclosing loop is at (the loop itself or the data set it goes through)
        here = (outputs.get(templates.LOOPS) or {}).get(source)
        if here is None:
            raise JobError(f"„Trenutni red petlje“ ({label}): ovaj zadatak nije u petlji koja prolazi kroz te redove.")
        r = here["red"]
        if isinstance(r, dict) and column not in r:
            raise JobError(f"Kolona „{column}“ ne postoji u trenutnom redu ({label}). Kolone: {', '.join(r)}.")
        return r[column] if isinstance(r, dict) else r
    if source not in outputs:
        raise JobError(f"Polje koristi {label}, ali on (još) nije vratio vrednost.")
    value = outputs[source]
    pick = ref.get("pick", "first")
    if pick == "value":
        return value
    if pick == "total":
        totals = value.get("ukupno") if isinstance(value, dict) else None
        if not isinstance(totals, dict) or column not in totals:
            raise JobError(f"{label.capitalize()} nema ukupan iznos „{column}“.")
        return totals[column]
    rows = value.get("redovi") if isinstance(value, dict) else value if isinstance(value, list) else None
    if rows is None:
        raise JobError(f"{label.capitalize()} nije vratio redove.")
    if pick == "count":
        return len(rows)

    def cell(r):
        if not isinstance(r, dict):
            return r
        if column not in r:
            raise JobError(f"Kolona „{column}“ ne postoji u rezultatu: {label}. Kolone: {', '.join(r)}.")
        return r[column]

    if pick == "all":
        return _Each([cell(r) for r in rows])
    index = 0 if pick == "first" else int(ref.get("row") or 1) - 1
    if not 0 <= index < len(rows):
        raise JobError(f"{label.capitalize()} je vratio {len(rows)} redova; red {index + 1} ne postoji.")
    return cell(rows[index])


def _merge(values: list):
    """One result from several runs of a task (one per row): row lists are joined."""
    if values and all(isinstance(v, dict) and isinstance(v.get("redovi"), list) for v in values):
        merged = {
            "kolone": values[0].get("kolone", []),
            "redovi": [row for v in values for row in v["redovi"]],
            "pokretanja": len(values),
            # What each run returned besides its rows (search text, totals, ...).
            "po_pokretanju": [{k: x for k, x in v.items() if k not in ("kolone", "redovi")} for v in values],
        }
        merged["broj"] = len(merged["redovi"])
        if all(isinstance(v.get("ukupno"), dict) for v in values):
            merged["ukupno"] = _sum_totals([v["ukupno"] for v in values])
        if any("zbir_odgovara" in v for v in values):
            merged["zbir_odgovara"] = all(v.get("zbir_odgovara", True) for v in values)
        return merged
    if not values:
        return {"kolone": [], "redovi": [], "broj": 0, "pokretanja": 0,
                "napomena": "Prethodni zadatak nije vratio nijedan red, pa ovaj nije pokrenut."}
    return values


def _sum_totals(totals: list[dict]) -> dict:
    """Add up amounts like "1.798,59" key by key (totals of several documents)."""
    sums: dict[str, float] = {}
    for total in totals:
        for key, text in total.items():
            amount = app_page.parse_amount(str(text))
            if amount is not None:
                sums[key] = sums.get(key, 0.0) + amount
    return {key: app_page.format_amount(value) for key, value in sums.items()}


def _jsonable(value):
    """A JSON copy of a task's value as it is now (the task may keep changing its own object), or its
    repr if it can't be represented as JSON (e.g. a WebElement or a circular structure)."""
    try:
        return json.loads(json.dumps(value))
    except (TypeError, ValueError):
        return repr(value)
