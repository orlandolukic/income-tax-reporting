import { createContext, ReactNode, useContext, useEffect, useId, useRef, useState } from "react";
import { createPortal } from "react-dom";
import {
  Branch, CheckValue, FilterField, FilterValue, isRef, isSecret, newId, newTask, PageInfo, ParamRef, ParamSpec, ParamValue, Task,
  TaskResult, TaskType,
} from "../api";
import { Check, CodeBlock, DateInput, NameSelect } from "../controls";
import { formatDuration, StatusBadge } from "./common";
import { canHold, DropTarget, duplicateTask, MAX_SUB_DEPTH, Slot, useDrag } from "./tree";
import { Kind, kindProblem, KindsContext } from "./kinds";

/** Where a task can take data from: an earlier task, or (in a subtask) the current row. */
export type Source = {
  id: string; // task id, or "@red"
  number: string; // as shown: "2", "2.1", "red"
  title: string;
  columns: string[];
  totals: string[];
  kind: "task" | "row";
  // Inside a loop that goes through this task's rows (the "Petlja" itself, its data set, or a task whose subtasks run
  // per row): its "Trenutni red petlje" can be used.
  current?: boolean;
  of?: string; // "Trenutni red": the task whose rows the loop goes through (for the column kinds)
};

const ROW = "@red";

/** Options read from the program (e.g. Podvrste per Vrsta) and whether the browser can read more now. */
export type Choices = { known: Record<string, Record<string, string[]>> };
export const ChoicesContext = createContext<Choices>({ known: {} });

/** The params with `name` changed; a "choice" param that depends on it is cleared if the new value's known options
 * don't include it (e.g. Podvrsta when Vrsta changes). */
function withParam(type: TaskType | undefined, params: Record<string, ParamValue>, name: string, value: ParamValue,
                   known: Choices["known"]): Record<string, ParamValue> {
  const next = { ...params, [name]: value };
  for (const spec of type?.params ?? []) {
    if (spec.kind !== "choice" || spec.depends !== name || !spec.choices) continue;
    const options = typeof value === "string" ? known[spec.choices]?.[value] : undefined;
    const current = next[spec.name];
    if (typeof current === "string" && current && !options?.includes(current)) next[spec.name] = "";
  }
  return next;
}

type Crumb = { id: string; number: string; title: string };

/** A later task "Nastavi" can jump to. */
type Sibling = { id: string; number: string; title: string };

/** What the tasks of a nested list (subtasks, or a condition's branch) share. */
type ListContext = {
  types: TaskType[];
  depth: number; // subtask depth of the tasks in the list (branches stay on their condition's depth)
  trail: Crumb[]; // the tasks they belong to, outermost first (shown at the top of their windows)
  inheritedRow?: Source; // "Trenutni red" of the enclosing row loop, if any
  pageColumns: string[];
  pageBefore: string | undefined;
  pages: Record<string, PageInfo>;
  // Later tasks outside the list that a "Nastavi" in it can jump to (after the condition / the opened
  // page it is in, up to its row loop); a row loop starts with none.
  jumpTargets: Sibling[];
};

type Props = {
  number: string; // "2", or "2.1" for a subtask
  nested?: boolean;
  depth?: number; // 0 for a task, 1 for its subtasks, ...
  inheritedRow?: Source; // "Trenutni red" of the enclosing row loop, if any
  trail?: Crumb[]; // the parent tasks, outermost first (shown at the top of a subtask's window)
  ownColumns: string[]; // columns of this task's rows (the current row's columns in its subtasks)
  index: number;
  count: number;
  task: Task;
  type: TaskType | undefined;
  types: TaskType[];
  result: TaskResult | undefined;
  sources: Source[]; // earlier tasks
  pageColumns: string[]; // columns of the page opened by the nearest earlier "Otvori stranicu"
  pageBefore: string | undefined;
  pages: Record<string, PageInfo>;
  jumpTargets?: Sibling[]; // later tasks a "Nastavi" here can jump to
  onChange: (patch: Partial<Task>) => void;
  onMove: (delta: number) => void;
  onRemove: () => void;
  onDuplicate: () => void;
};

const CONDITION_COLUMNS = ["Grana", "Provera", "Leva vrednost", "Ispunjeno"];

export default function TaskCard(props: Props) {
  const { index, count, task, type, types, result, onChange, onMove, onRemove, onDuplicate } = props;
  const subtasks = task.subtasks ?? [];
  const trail: Crumb[] = [...(props.trail ?? []), { id: task.id, number: props.number, title: task.title || type?.title || task.type }];
  const isCondition = task.type === "condition";

  // How the subtasks run: for each row of this task's result, or once after it (on the page it opened).
  const childMode: "rows" | "once" | null = type?.subtasksWhen
    ? task.params[type.subtasksWhen[0]] === type.subtasksWhen[1]
      ? "once"
      : null
    : type?.subtasksOnce
      ? "once"
      : type?.returnsRows
        ? "rows"
        : null;
  const depth = props.depth ?? 0;
  const rowSource: Source | undefined =
    childMode === "rows"
      ? {
          id: ROW, number: "red", kind: "row", columns: props.ownColumns, totals: [], of: task.id,
          title: `Trenutni red (red iz zadatka #${props.number})`,
        }
      : props.inheritedRow;

  // What a subtask can use: the current row, earlier tasks, this task and earlier subtasks.
  function childSources(j: number): Source[] {
    const self: Source = {
      id: task.id, number: props.number, kind: "task", columns: props.ownColumns, totals: type?.totals ?? [],
      title: `${task.title || type?.title || task.type} (${childMode === "rows" ? "svi redovi" : "ovaj red"})`,
      current: childMode === "rows",
    };
    return [
      ...(rowSource ? [rowSource] : []),
      ...withLoopSource(props.sources.filter((s) => s.kind !== "row"), childMode === "rows" ? task : undefined),
      self,
      ...earlierSources(subtasks, j, (k) => `${props.number}.${k + 1}`, types, result, " (ovaj red)"),
    ];
  }

  // The task's fields, by section (Param.group; "" = above the sections), in the order of their first field.
  const fieldGroups: Record<string, ParamSpec[]> = { "": [] };
  for (const p of type?.params.filter((p) => isShown(p, type, task)) ?? []) (fieldGroups[p.group ?? ""] ??= []).push(p);
  const field = (p: ParamSpec) => (
    <ParamField
      key={p.name}
      spec={p}
      value={task.params[p.name] ?? ""}
      sources={props.sources}
      pageColumns={props.pageColumns}
      pageBefore={props.pageBefore}
      jumpTargets={props.jumpTargets ?? []}
      filterFields={p.fields?.length ? p.fields : (props.pages[props.pageBefore ?? ""]?.filteri ?? [])}
      params={task.params}
      onChange={(v) => onChange({ params: withParam(type!, task.params, p.name, v, choices.known) })}
    />
  );

  function changeType(id: string) {
    const next = types.find((t) => t.id === id);
    if (!next) return;
    // Keep values of params the new type also has.
    const params = Object.fromEntries(next.params.map((p) => [p.name, task.params[p.name] ?? p.default]));
    // Only a condition has branches (undefined keys are left out when the job is saved).
    const branches =
      id === "condition"
        ? { then: task.then ?? [], elifs: task.elifs ?? [], else: task.else ?? [] }
        : { then: undefined, elifs: undefined, else: undefined };
    onChange({ type: id, params, ...branches });
  }

  const drop = useDropOn(task.id, canHold(task, type), "head");
  const choices = useContext(ChoicesContext);

  const listContext: ListContext = {
    types, depth, trail, inheritedRow: rowSource, pageColumns: props.pageColumns, pageBefore: props.pageBefore, pages: props.pages,
    jumpTargets: props.jumpTargets ?? [],
  };

  return (
    <li className={`task ${result ? `r-${result.status}` : ""} ${result?.aktivan ? "is-active" : ""} ${drop.className}`}>
      <div className="task-head" {...drop.handlers}>
        <DragHandle id={task.id} />
        <span className="task-no">{props.number}</span>
        <select value={task.type} onChange={(e) => changeType(e.target.value)} aria-label="Vrsta zadatka">
          {!type && <option value={task.type}>Nepoznato: {task.type}</option>}
          <TypeOptions types={types} />
        </select>
        {type && !type.implemented && <span className="badge soon">uskoro</span>}
        <span className="spacer" />
        <button className="icon" disabled={index === 0} onClick={() => onMove(-1)} aria-label="Pomeri gore" title="Pomeri gore">
          ↑
        </button>
        <button className="icon" disabled={index === count - 1} onClick={() => onMove(1)} aria-label="Pomeri dole" title="Pomeri dole">
          ↓
        </button>
        <button className="icon" onClick={onDuplicate} aria-label="Dupliraj zadatak" title="Dupliraj zadatak (kopija ispod, sa svim podzadacima)">
          ⧉
        </button>
        <button className="icon" onClick={onRemove} aria-label="Ukloni zadatak" title="Ukloni zadatak">
          ✕
        </button>
      </div>
      {type && <p className="muted small task-desc">{type.description}</p>}
      <div className="task-fields">
        <label>
          <span>
            Naziv zadatka <span className="muted small">(opciono)</span>
          </span>
          <input value={task.title} placeholder={type?.title} onChange={(e) => onChange({ title: e.target.value })} />
        </label>
        {!isCondition && fieldGroups[""]?.map(field)}
        {type && type.params.length === 0 && <p className="muted small">Ovaj zadatak nema podešavanja.</p>}
      </div>
      {!isCondition &&
        Object.entries(fieldGroups)
          .filter(([group]) => group)
          .map(([group, specs]) => (
            <fieldset key={group} className="param-group">
              <legend>{group}</legend>
              <div className="task-fields">{specs.map(field)}</div>
            </fieldset>
          ))}
      {((task.type === "continue" && continueMode(task) !== "jump") || task.type === "break") && !props.inheritedRow && (
        <p className="error small">
          „Nastavi“ (sledeći red) i „Prekini“ rade samo u petlji: u „Petlji“ ili u podzadacima koji se izvršavaju za
          svaki red (npr. pod „Pretragom“). Ovde bi posao stao sa greškom.
        </p>
      )}
      {type?.breakerWhen && (
        <Check className="breaker" checked={!!task.breaker} onChange={(c) => onChange({ breaker: c })}>
          
          <span>
            <strong>Prekidač</strong> — ako {type.breakerWhen},{" "}
            {props.nested
              ? "ostali podzadaci za taj red se preskaču i prelazi se na sledeći red."
              : "ceo posao se prekida (sledeći zadaci se ne izvršavaju)."}
          </span>
        </Check>
      )}
      {task.type === "open_menu" && typeof task.params.item === "string" && task.params.item && (
        <PageFacts path={task.params.item} info={props.pages[task.params.item]} />
      )}
      {result && <TaskResultView result={result} />}
      {isCondition && type && (
        <Branches
          task={task}
          type={type}
          number={props.number}
          result={result}
          sources={props.sources}
          ctx={listContext}
          onChange={onChange}
        />
      )}
      {depth >= MAX_SUB_DEPTH && childMode && (
        <p className="muted small">Ovde ne mogu podzadaci: najviše {MAX_SUB_DEPTH} nivoa podzadataka.</p>
      )}
      {depth < MAX_SUB_DEPTH && (childMode || (type?.subtasksWhen && subtasks.length > 0)) && (
        <div className={`subtasks ${childMode ? "" : "off"}`}>
          <div className="subtasks-head">
            <strong>{task.type === "loop" ? "Za svaki red" : childMode === "once" ? "Podzadaci na otvorenoj stranici" : "Podzadaci"}</strong>
            <span className="muted small">
              {childMode === "rows" &&
                "Izvršavaju se za svaki red rezultata ovog zadatka, redom. U njima je dostupan „Trenutni red“ i rezultati prethodnih podzadataka za isti red."}
              {childMode === "once" &&
                "Izvršavaju se jednom, kad se stranica otvori. Na kraju program sam klikne „Nazad“ ako to nije uradio zadatak „Nazad“."}
              {!childMode && "Isključeno: podzadaci se izvršavaju samo kad je uključeno „Klikni na finansijski nalog“."}
            </span>
          </div>
          <SubtaskList
            slot={{ parent: task.id, key: "subtasks" }}
            tasks={subtasks}
            numberOf={(j) => `${props.number}.${j + 1}`}
            parentResult={result}
            sourcesAt={childSources}
            // A jump never leaves a row loop; from the subtasks of an opened page it can go past this task.
            ctx={{ ...listContext, depth: depth + 1, jumpTargets: childMode === "rows" ? [] : listContext.jumpTargets }}
            addLabel={task.type === "loop" ? "+ Dodaj zadatak u petlju" : "+ Dodaj podzadatak"}
            defaultType={task.type === "loop" ? "empty" : "fiscal_receipts"}
            onChange={(next) => onChange({ subtasks: next })}
          />
        </div>
      )}
    </li>
  );
}

/** The columns of a "Petlja": those of the data set it loops over (undefined for other tasks). */
export function loopColumns(t: Task, sources: Source[]): string[] | undefined {
  if (t.type !== "loop") return undefined;
  const ref = t.params.izvor;
  return (isRef(ref) && sources.find((s) => s.id === ref.ref && s.kind !== "row")?.columns) || [];
}

/** Sources for the tasks of a list that come before task `j`: each earlier task, and the tasks inside
 * the branches of an earlier "Uslov" (they only have a value if their branch ran). */
function earlierSources(
  list: Task[], j: number, numberOf: (k: number) => string, types: TaskType[], parent: TaskResult | undefined, suffix = "",
): Source[] {
  const one = (t: Task, number: string, res: TaskResult | undefined): Source[] => {
    const type = types.find((x) => x.id === t.type);
    const value = res?.value as { kolone?: string[] } | null | undefined;
    const own: Source = {
      id: t.id, number, kind: "task", title: `${t.title || type?.title || t.type}${suffix}`,
      columns: value?.kolone?.length ? value.kolone : (type?.outputColumns ?? []), totals: type?.totals ?? [],
    };
    if (t.type !== "condition") return [own];
    return [
      own,
      ...branchesOf(t).flatMap((b) =>
        b.tasks.flatMap((c, k) => one(c, `${number}.${b.offset + k + 1}`, res?.subtasks?.find((r) => r.id === c.id))),
      ),
    ];
  };
  return list.slice(0, j).flatMap((t, k) => one(t, numberOf(k), parent?.subtasks?.find((r) => r.id === t.id)));
}

type BranchInfo = {
  key: string; // "then", the INAČE AKO branch's id, or "else" (as in the run result's "grane")
  kind: "then" | "elif" | "else";
  label: string;
  tasks: Task[];
  offset: number; // tasks before this branch's first one (numbering goes on across branches)
  elif?: Branch;
};

/** The branches of a "Uslov" in order: AKO, each INAČE AKO, INAČE. */
function branchesOf(task: Task): BranchInfo[] {
  const out: BranchInfo[] = [];
  let offset = 0;
  const add = (b: Omit<BranchInfo, "offset">) => {
    out.push({ ...b, offset });
    offset += b.tasks.length;
  };
  add({ key: "then", kind: "then", label: "AKO", tasks: task.then ?? [] });
  for (const elif of task.elifs ?? []) add({ key: elif.id, kind: "elif", label: "INAČE AKO", tasks: elif.then, elif });
  add({ key: "else", kind: "else", label: "INAČE", tasks: task.else ?? [] });
  return out;
}

/** The branches of a "Uslov", each with its tasks indented under it. In its own card the checks of each
 * branch are edited here and tasks can be added; `compact` is the outline shown under the condition's
 * line in a list of subtasks (checks as text, empty INAČE hidden). */
function Branches(props: {
  task: Task;
  type: TaskType | undefined;
  number: string;
  result: TaskResult | undefined;
  sources: Source[]; // what the condition itself can use
  ctx: ListContext; // for the tasks in the branches (trail includes the condition)
  compact?: boolean;
  onChange: (patch: Partial<Task>) => void;
}) {
  const { task, type, number, result, sources, ctx, compact, onChange } = props;
  const branches = branchesOf(task);
  const drag = useDrag();
  const self: Source = {
    id: task.id, number, kind: "task", columns: CONDITION_COLUMNS, totals: [],
    title: task.title || type?.title || "Uslov",
  };

  function setTasks(b: BranchInfo, next: Task[]) {
    if (b.kind === "then") onChange({ then: next });
    else if (b.kind === "else") onChange({ else: next });
    else onChange({ elifs: (task.elifs ?? []).map((e) => (e.id === b.key ? { ...e, then: next } : e)) });
  }

  function setElif(id: string, patch: Partial<Branch>) {
    onChange({ elifs: (task.elifs ?? []).map((e) => (e.id === id ? { ...e, ...patch } : e)) });
  }

  function addElif() {
    const params = Object.fromEntries((type?.params ?? []).map((p) => [p.name, p.default]));
    onChange({ elifs: [...(task.elifs ?? []), { id: newId(), params, then: [] }] });
  }

  const checkFields = (params: Record<string, ParamValue>, set: (params: Record<string, ParamValue>) => void) => (
    <div className="task-fields branch-checks">
      {(type?.params ?? []).map((p) => (
        <ParamField
          key={p.name}
          spec={p}
          value={params[p.name] ?? ""}
          sources={sources}
          pageColumns={ctx.pageColumns}
          pageBefore={ctx.pageBefore}
          jumpTargets={[]}
          filterFields={[]}
          onChange={(v) => set({ ...params, [p.name]: v })}
        />
      ))}
    </div>
  );

  return (
    <div className={`if-block ${compact ? "compact" : ""}`}>
      {branches.map((b) => {
        // An empty INAČE is hidden in the outline, except while a task is dragged that can be dropped into it.
        const elseDrop = !!drag?.dragging && !drag.blocker({ kind: "end", slot: { parent: task.id, key: "else" } });
        if (compact && b.kind === "else" && b.tasks.length === 0 && !elseDrop) return null;
        const runs = result?.grane?.[b.key];
        const params = b.kind === "then" ? task.params : b.elif?.params;
        return (
          <div key={b.key} className={`branch b-${b.kind}`}>
            <div className="branch-head">
              <span className="kw">{b.label}</span>
              {compact ? (
                b.kind !== "else" && <span className="branch-summary small">{checksSummary(params ?? {})}</span>
              ) : (
                <span className="muted small">
                  {b.kind === "then" && "ovi uslovi važe — izvršavaju se zadaci ispod"}
                  {b.kind === "elif" && "prethodni nisu ispunjeni, a ovi jesu"}
                  {b.kind === "else" && "nijedan uslov nije ispunjen"}
                </span>
              )}
              {runs !== undefined && (
                <span className="branch-count small" title="Koliko puta je ova grana izabrana u poslednjem pokretanju">
                  {runs}×
                </span>
              )}
              {!compact && b.kind === "elif" && (
                <>
                  <span className="spacer" />
                  <button
                    className="icon"
                    onClick={() => onChange({ elifs: (task.elifs ?? []).filter((e) => e.id !== b.key) })}
                    aria-label="Ukloni granu"
                    title="Ukloni granu „Inače ako“ i njene zadatke"
                  >
                    ✕
                  </button>
                </>
              )}
            </div>
            {!compact && b.kind === "then" && checkFields(task.params, (params) => onChange({ params }))}
            {!compact && b.kind === "elif" && checkFields(b.elif!.params, (params) => setElif(b.key, { params }))}
            <div className="branch-body">
              {b.tasks.length === 0 && compact ? (
                <DropEnd slot={{ parent: task.id, key: b.key }} fallback={<span className="muted small">ništa</span>} />
              ) : (
                <SubtaskList
                  slot={{ parent: task.id, key: b.key }}
                  tasks={b.tasks}
                  numberOf={(j) => `${number}.${b.offset + j + 1}`}
                  parentResult={result}
                  sourcesAt={(j) => [
                    ...sources,
                    self,
                    ...earlierSources(b.tasks, j, (k) => `${number}.${b.offset + k + 1}`, ctx.types, result),
                  ]}
                  ctx={ctx}
                  addLabel={compact ? undefined : "+ Dodaj zadatak u granu"}
                  defaultType={ctx.inheritedRow ? "continue" : "empty"}
                  emptyText={b.kind === "else" ? "Nema zadataka: ako nijedan uslov nije ispunjen, ide se dalje." : "Nema zadataka."}
                  onChange={(next) => setTasks(b, next)}
                />
              )}
            </div>
          </div>
        );
      })}
      {!compact && (
        <div className="add-task branch-add">
          <button onClick={addElif}>+ Dodaj „Inače ako“</button>
        </div>
      )}
    </div>
  );
}

/** Tasks listed one per line (subtasks, or the tasks of a condition's branch); each opens in a window.
 * A "Uslov" line shows its branches indented under it. */
function SubtaskList(props: {
  slot: Slot; // which list of the job these tasks are (for drag and drop)
  tasks: Task[];
  numberOf: (j: number) => string;
  parentResult: TaskResult | undefined; // the entry whose subtasks hold these tasks' results
  sourcesAt: (j: number) => Source[];
  ctx: ListContext;
  addLabel?: string; // shows the "add" control
  defaultType: string;
  emptyText?: string;
  onChange: (tasks: Task[]) => void;
}) {
  const { tasks, ctx, onChange } = props;
  const { types } = ctx;
  const typeOf = (id: string) => types.find((t) => t.id === id);
  const [addType, setAddType] = useState(typeOf(props.defaultType)?.id ?? types[0]?.id ?? "");
  // The task whose window is open.
  const [open, setOpen] = useState<string | null>(null);

  function add() {
    const t = typeOf(addType);
    if (!t) return;
    const task = newTask(t);
    onChange([...tasks, task]);
    setOpen(task.id);
  }

  function columnsOf(t: Task, res: TaskResult | undefined, j: number): string[] {
    const value = res?.value as { kolone?: string[] } | null | undefined;
    if (value?.kolone?.length) return value.kolone;
    return loopColumns(t, props.sourcesAt(j)) ?? typeOf(t.type)?.outputColumns ?? [];
  }

  return (
    <>
      {tasks.length === 0 && props.emptyText && props.addLabel && <p className="muted small branch-empty">{props.emptyText}</p>}
      {tasks.length > 0 && (
        <ol className="subtask-list">
          {tasks.map((sub, j) => {
            const subType = typeOf(sub.type);
            const subResult = props.parentResult?.subtasks?.find((r) => r.id === sub.id);
            const number = props.numberOf(j);
            const name = sub.title || subType?.title || sub.type;
            const nested = sub.subtasks?.length ?? 0;
            const update = (patch: Partial<Task>) => onChange(tasks.map((s, k) => (k === j ? { ...s, ...patch } : s)));
            const move = (delta: number) => {
              const next = [...tasks];
              const [moved] = next.splice(j, 1);
              next.splice(j + delta, 0, moved);
              onChange(next);
            };
            const remove = () => onChange(tasks.filter((_, k) => k !== j));
            const duplicate = () => onChange([...tasks.slice(0, j + 1), duplicateTask(sub), ...tasks.slice(j + 1)]);
            const crumb = { id: sub.id, number, title: name };
            // Where a "Nastavi" here can jump: later tasks of this list, then those after the list.
            const targets: Sibling[] = [
              ...tasks.slice(j + 1).map((t, k) => ({
                id: t.id, number: props.numberOf(j + k + 1), title: t.title || typeOf(t.type)?.title || t.type,
              })),
              ...ctx.jumpTargets,
            ];
            return (
              <li key={sub.id} className="subtask-item">
                <SubtaskRow id={sub.id} holds={canHold(sub, subType)} className={`${subResult ? `r-${subResult.status}` : ""} ${hasActive(subResult) ? "is-active" : ""}`}>
                  <button className="subtask-open" onClick={() => setOpen(sub.id)} title="Otvori zadatak">
                    <span className="task-no">{number}</span>
                    <span className="subtask-name">
                      <strong>{name}</strong>
                      {sub.title && subType && <span className="muted small"> · {subType.title}</span>}
                      {sub.type === "condition" && <span className="muted small"> · {(sub.elifs?.length ?? 0) + 2} grane</span>}
                      {sub.breaker && <span className="badge breaker-badge">prekidač</span>}
                      {sub.type === "continue" && <span className="badge flow-badge">{continueBadge(sub, targets)}</span>}
                      {sub.type === "break" && <span className="badge flow-badge">⤓ izlaz iz petlje</span>}
                      {sub.type === "stop" && <span className="badge flow-badge stop">■ kraj posla</span>}
                      {sub.type === "loop" && <span className="muted small"> · {loopSourceText(sub, props.sourcesAt(j))}</span>}
                      {nested > 0 && sub.type !== "loop" && <span className="muted small"> · podzadaci: {nested}</span>}
                    </span>
                    {subResult?.status === "running" && subResult.progress && (
                      <span className="subtask-progress small">{subResult.progress}</span>
                    )}
                    {subResult && <StatusBadge status={subResult.status} />}
                    <span className="subtask-edit">Uredi ›</span>
                  </button>
                  <button className="icon" disabled={j === 0} onClick={() => move(-1)} aria-label="Pomeri gore" title="Pomeri gore">
                    ↑
                  </button>
                  <button className="icon" disabled={j === tasks.length - 1} onClick={() => move(1)} aria-label="Pomeri dole" title="Pomeri dole">
                    ↓
                  </button>
                  <button className="icon" onClick={duplicate} aria-label="Dupliraj zadatak" title="Dupliraj zadatak (kopija ispod, sa svim podzadacima)">
                    ⧉
                  </button>
                  <MoveOut id={sub.id} owner={ctx.trail[ctx.trail.length - 1]} />
                  <button className="icon" onClick={remove} aria-label="Ukloni zadatak" title="Ukloni zadatak">
                    ✕
                  </button>
                </SubtaskRow>
                {sub.type === "condition" && (
                  <Branches
                    compact
                    task={sub}
                    type={subType}
                    number={number}
                    result={subResult}
                    sources={props.sourcesAt(j)}
                    ctx={{ ...ctx, trail: [...ctx.trail, crumb], jumpTargets: targets }}
                    onChange={update}
                  />
                )}
                {sub.type === "loop" && ctx.depth >= MAX_SUB_DEPTH && (
                  <p className="muted small loop-body">Petlja ovde ne može imati zadatke: najviše {MAX_SUB_DEPTH} nivoa podzadataka.</p>
                )}
                {sub.type === "loop" && ctx.depth < MAX_SUB_DEPTH && (
                  <LoopBody
                    loop={sub}
                    number={number}
                    result={subResult}
                    columns={columnsOf(sub, subResult, j)}
                    outer={props.sourcesAt(j)}
                    ctx={{ ...ctx, trail: [...ctx.trail, crumb] }}
                    onChange={(subtasks) => update({ subtasks })}
                  />
                )}
                {open === sub.id && (
                  <Modal id={sub.id} trail={ctx.trail} number={number} title={name} onClose={() => setOpen(null)}>
                    <ol className="tasks">
                      <TaskCard
                        nested
                        depth={ctx.depth}
                        trail={ctx.trail}
                        inheritedRow={ctx.inheritedRow}
                        number={number}
                        ownColumns={columnsOf(sub, subResult, j)}
                        index={j}
                        count={tasks.length}
                        task={sub}
                        type={subType}
                        types={types}
                        result={subResult}
                        sources={props.sourcesAt(j)}
                        pageColumns={ctx.pageColumns}
                        pageBefore={ctx.pageBefore}
                        pages={ctx.pages}
                        jumpTargets={targets}
                        onChange={update}
                        onMove={move}
                        onRemove={() => {
                          setOpen(null);
                          remove();
                        }}
                        onDuplicate={duplicate}
                      />
                    </ol>
                  </Modal>
                )}
              </li>
            );
          })}
        </ol>
      )}
      <DropEnd slot={props.slot} />
      {props.addLabel && (
        <div className="add-task">
          <select value={addType} onChange={(e) => setAddType(e.target.value)} aria-label="Vrsta zadatka">
            <TypeOptions types={types} soon />
          </select>
          <button onClick={add}>{props.addLabel}</button>
        </div>
      )}
    </>
  );
}

/** The tasks of a "Petlja" shown under its line in a list, indented: they run for each row of its data set. */
function LoopBody(props: {
  loop: Task;
  number: string;
  result: TaskResult | undefined;
  columns: string[]; // of its rows
  outer: Source[]; // what the loop itself can use
  ctx: ListContext; // trail includes the loop
  onChange: (subtasks: Task[]) => void;
}) {
  const { loop, number, result, ctx } = props;
  const tasks = loop.subtasks ?? [];
  const title = loop.title || ctx.types.find((t) => t.id === "loop")?.title || "Petlja";
  const row: Source = {
    id: ROW, number: "red", kind: "row", columns: props.columns, totals: [], of: loop.id,
    title: `Trenutni red (red iz zadatka #${number})`,
  };
  const self: Source = {
    id: loop.id, number, kind: "task", columns: props.columns, totals: [], title: `${title} (svi redovi)`, current: true,
  };
  return (
    <div className="loop-body">
      <div className="loop-head">
        <span className="kw">ZA SVAKI RED</span>
        <span className="muted small">{loopSourceText(loop, props.outer)}</span>
      </div>
      <SubtaskList
        slot={{ parent: loop.id, key: "subtasks" }}
        tasks={tasks}
        numberOf={(k) => `${number}.${k + 1}`}
        parentResult={result}
        sourcesAt={(k) => [
          row,
          ...withLoopSource(props.outer.filter((s) => s.kind !== "row"), loop),
          self,
          ...earlierSources(tasks, k, (m) => `${number}.${m + 1}`, ctx.types, result, " (ovaj red)"),
        ]}
        // A jump never leaves a row loop.
        ctx={{ ...ctx, depth: ctx.depth + 1, inheritedRow: row, jumpTargets: [] }}
        addLabel="+ Dodaj zadatak u petlju"
        defaultType="empty"
        emptyText="Petlja još nema zadataka."
        onChange={props.onChange}
      />
    </div>
  );
}

/** The sources with the data set a "Petlja" goes through marked as `current` (inside the loop its row i is the loop's
 * row i). */
function withLoopSource(sources: Source[], loop: Task | undefined): Source[] {
  const ref = loop?.type === "loop" ? loop.params.izvor : undefined;
  return isRef(ref) ? sources.map((s) => (s.id === ref.ref ? { ...s, current: true } : s)) : sources;
}

/** Kind of the value a reference or token gives: a column of a task / the current row, a total, a count. */
function refKind(kinds: Record<string, Record<string, Kind>>, source: Source | undefined, pick: string, column: string): Kind | undefined {
  if (!source) return undefined;
  if (pick === "total" || pick === "count") return "number";
  if (pick === "value") return undefined;
  return kinds[source.kind === "row" ? (source.of ?? "") : source.id]?.[column];
}

/** "redovi iz #2 Pretraga" for a loop's line. */
function loopSourceText(loop: Task, sources: Source[]): string {
  const ref = loop.params.izvor;
  const source = isRef(ref) ? sources.find((s) => s.id === ref.ref && s.kind !== "row") : undefined;
  return source ? `redovi iz #${source.number} ${source.title.replace(/ \((svi redovi|ovaj red)\)$/, "")}` : "izaberite skup podataka";
}

/** Options that depend on another param (e.g. Podvrsta on Vrsta): the ones known for that value (read once from the
 * program, kept in the code), a typed one, or empty = what the program sets. */
function ChoiceField(props: { spec: ParamSpec; value: string; depends: ParamValue | undefined; onChange: (v: string) => void }) {
  const { spec, value } = props;
  const { known } = useContext(ChoicesContext);
  const key = typeof props.depends === "string" ? props.depends : "";
  const options = key && spec.choices ? known[spec.choices]?.[key] : undefined;

  return (
    <span className="choice-field">
      <NameSelect value={value} options={options ?? []} placeholder="kako program postavi" onChange={props.onChange} ariaLabel={spec.label} />
      {!key && <span className="muted small">Prvo izaberite {spec.depends}.</span>}
      {options && value && !options.includes(value) && (
        <span className="error small">„{value}“ nije među opcijama za „{key}“: {options.join(", ")}.</span>
      )}
    </span>
  );
}

/** Kinds of value a token can take from a source (see tim_automation/jobs/templates.py). */
const TOKEN_PICKS: { id: string; label: string; needs: "column" | "total" | "none"; rows?: boolean; loop?: boolean }[] = [
  { id: "first", label: "kolona — prvi red (u petlji: ovaj red)", needs: "column", rows: true },
  { id: "i", label: "kolona — red i (trenutni prolaz petlje)", needs: "column", rows: true, loop: true },
  { id: "k", label: "kolona — red broj…", needs: "column", rows: true },
  { id: "all", label: "kolona — svi redovi (spojeno zarezom)", needs: "column", rows: true },
  { id: "count", label: "broj redova", needs: "none", rows: true },
  { id: "total", label: "ukupan iznos", needs: "total" },
  { id: "field", label: "polje vrednosti (npr. nalog)", needs: "column" },
];

function makeToken(source: Source, pick: string, name: string, k: number): string {
  if (source.kind === "row") return pick === "pass" ? "$i$" : `$red.${name}$`;
  const n = source.number;
  // Inside a loop that goes through this task's rows, $n.Kolona$ is the loop's current row; the first row is [1].
  if (source.current && pick === "first") return `$${n}[1].${name}$`;
  switch (pick) {
    case "i": return `$${n}[i].${name}$`;
    case "k": return `$${n}[${k}].${name}$`;
    case "all": return `$${n}[*].${name}$`;
    case "count": return `$${n}[#]$`;
    case "total": return `$${n}.ukupno.${name}$`;
    default: return `$${n}.${name}$`;
  }
}

/** Problems with the "$...$" tokens of a text: unknown tasks, "Trenutni red" / [i] outside a loop. */
function tokenProblems(text: string, sources: Source[], expect?: string, kinds: Record<string, Record<string, Kind>> = {}): string[] {
  const inLoop = sources.some((s) => s.kind === "row");
  const numbers = new Set(sources.filter((s) => s.kind !== "row").map((s) => s.number));
  const problems: string[] = [];
  for (const m of text.matchAll(/\$([^$]*)\$/g)) {
    const body = m[1].trim();
    if (!body) continue;
    if (body === "i" || body.startsWith("red.")) {
      if (!inLoop) problems.push(`${m[0]}: postoji samo u petlji.`);
      continue;
    }
    const t = /^(\d+(?:\.\d+)*)(\[(\*|#|i|\d+)\])?(\..+)?$/.exec(body);
    if (!t) problems.push(`${m[0]}: nije ispravna oznaka.`);
    else if (!numbers.has(t[1])) problems.push(`${m[0]}: zadatak #${t[1]} nije pre ovog.`);
    else if (t[3] === "i" && !inLoop) problems.push(`${m[0]}: [i] postoji samo u petlji.`);
    else if (t[4]) {
      // A column the task doesn't have. Fields of the value itself ($2.3.nalog$, $2.1.ukupno.Virman$) are lower case.
      const name = t[4].slice(1);
      const source = sources.find((s) => s.kind !== "row" && s.number === t[1]);
      if (source?.columns.length && /^\p{Lu}/u.test(name) && !source.columns.includes(name)) {
        problems.push(`${m[0]}: zadatak #${t[1]} nema kolonu „${name}“. Ima: ${source.columns.join(", ")}.`);
      }
    }
  }
  for (const m of text.matchAll(/\$red\.([^$]+)\$/g)) {
    const row = sources.find((s) => s.kind === "row");
    if (row?.columns.length && !row.columns.includes(m[1].trim())) {
      problems.push(`${m[0]}: trenutni red nema kolonu „${m[1].trim()}“. Ima: ${row.columns.join(", ")}.`);
    }
  }
  // A number or date field holding just one value (maybe with a sign): it must be a number / date.
  const single = /^[-+]?\s*\$([^$]+)\$$/.exec(text.trim());
  if (single && (expect === "number" || expect === "date")) {
    const b = single[1].trim();
    let got: Kind | undefined;
    let what = `${single[0].replace(/^[-+]\s*/, "")}`;
    if (b.startsWith("red.")) {
      got = refKind(kinds, sources.find((s) => s.kind === "row"), "first", b.slice(4));
    } else if (b === "i") {
      got = "number";
    } else {
      const m = /^(\d+(?:\.\d+)*)(\[(\*|#|i|\d+)\])?(\..+)?$/.exec(b);
      const source = m ? sources.find((s) => s.kind !== "row" && s.number === m[1]) : undefined;
      if (m && m[3] === "#") got = "number";
      else if (m && m[4]?.startsWith(".ukupno.")) got = "number";
      else if (m && m[4] && m[3] !== "*") got = refKind(kinds, source, "first", m[4].slice(1));
      what = `${what} (${m?.[4] ? `kolona „${m[4].slice(1)}“` : "vrednost"})`;
    }
    const problem = kindProblem(what, got, expect);
    if (problem) problems.push(problem);
  }
  return problems;
}

/** "＄ Umetni vrednost": build a token for a value of an earlier task (or the current row) and insert it. */
function TokenTools({ text, sources, expect, onInsert }: { text: string; sources: Source[]; expect?: string; onInsert: (token: string) => void }) {
  const [open, setOpen] = useState(false);
  const [sourceId, setSourceId] = useState(sources[sources.length - 1]?.id ?? "");
  const [pick, setPick] = useState("first");
  const [name, setName] = useState("");
  const [k, setK] = useState(1);
  const source = sources.find((s) => s.id === sourceId) ?? sources[0];
  const inLoop = sources.some((s) => s.kind === "row");
  const picks =
    source?.kind === "row"
      ? [{ id: "column", label: "kolona trenutnog reda", needs: "column" as const }, { id: "pass", label: "broj prolaza petlje ($i$)", needs: "none" as const }]
      : [
          ...(source?.current ? [{ id: "current", label: "kolona — trenutni red petlje", needs: "column" as const }] : []),
          ...TOKEN_PICKS.filter((p) => (!p.loop || inLoop) && (p.id !== "total" || source?.totals.length)).map((p) =>
            source?.current && p.id === "first" ? { ...p, label: "kolona — prvi red" } : p,
          ),
        ];
  const chosen = picks.find((p) => p.id === pick) ?? picks[0];
  const names = chosen?.needs === "total" ? (source?.totals ?? []) : (source?.columns ?? []);
  const ready = !!source && !!chosen && (chosen.needs === "none" || !!name);
  const token = source && chosen ? makeToken(source, chosen.id, name, k) : "";
  const kinds = useContext(KindsContext);
  const problems = tokenProblems(text, sources, expect, kinds);

  return (
    <span className="token-tools" onClick={(e) => e.preventDefault()}>
      {problems.map((p) => (
        <span key={p} className="error small">
          {p}
        </span>
      ))}
      {!open ? (
        <button type="button" className="link small" onClick={() => setOpen(true)} title="Vrednost iz ranijeg zadatka ili trenutnog reda">
          ＄ Umetni vrednost
        </button>
      ) : (
        <span className="token-panel">
          <select value={source?.id ?? ""} onChange={(e) => { setSourceId(e.target.value); setName(""); }} aria-label="Izvor vrednosti">
            {sources.map((s) => (
              <option key={s.id} value={s.id}>
                {s.kind === "row" ? s.title : `#${s.number} ${s.title}`}
              </option>
            ))}
          </select>
          <select value={chosen?.id ?? ""} onChange={(e) => { setPick(e.target.value); setName(""); }} aria-label="Šta">
            {picks.map((p) => (
              <option key={p.id} value={p.id}>
                {p.label}
              </option>
            ))}
          </select>
          {chosen?.id === "k" && (
            <input type="number" min={1} className="row-no" value={k} onChange={(e) => setK(Number(e.target.value) || 1)} aria-label="Broj reda" />
          )}
          {chosen?.needs !== "none" && (
            <NameSelect value={name} options={names} placeholder={chosen?.needs === "total" ? "iznos" : "kolona"} onChange={setName} ariaLabel="Kolona" strict={names.length > 0} />
          )}
          <code className="token-preview">{ready ? token : "…"}</code>
          <button type="button" className="small-button" disabled={!ready} onClick={() => { onInsert(token); setOpen(false); }}>
            Umetni
          </button>
          <button type="button" className="link small" onClick={() => setOpen(false)}>
            Zatvori
          </button>
        </span>
      )}
    </span>
  );
}

/** "next" (go on with the next row), "exit" (leave the row loop) or "jump" (to a chosen later task). */
function continueMode(task: Task): "next" | "exit" | "jump" {
  const mode = String(task.params.mode || "");
  return mode.startsWith("Izađi") ? "exit" : mode.startsWith("Skoči") ? "jump" : "next";
}

function continueBadge(task: Task, targets: Sibling[]): string {
  const mode = continueMode(task);
  if (mode === "exit") return "⤓ izlaz iz petlje";
  if (mode === "next") return "↪ sledeći red";
  const target = targets.find((t) => t.id === task.params.target);
  return target ? `→ skok na #${target.number}` : "→ skok (izaberite zadatak)";
}

const OPERATOR_SIGNS: Record<string, string> = {
  Jednako: "=", "Različito od": "≠", "Veće od": ">", "Veće ili jednako": "≥", "Manje od": "<", "Manje ili jednako": "≤",
};

/** A condition's checks as one line of text, e.g. "Virman > 0 i Dokument je prazno". */
function checksSummary(params: Record<string, ParamValue>): string {
  const checks = Array.isArray(params.checks) ? (params.checks as CheckValue[]) : [];
  if (!checks.length) return "(nema provera)";
  const side = (v: string | ParamRef | undefined): string => {
    if (v === undefined || v === "") return "…";
    if (typeof v === "string") return v;
    if (v.pick === "count") return "broj redova";
    if (v.pick === "total") return `ukupno ${v.column ?? ""}`;
    if (v.pick === "value") return "vrednost";
    return v.column || "…";
  };
  const parts = checks.map((c) => {
    const op = c.operator || "";
    if (op === "Je prazno" || op === "Nije prazno") return `${side(c.levo)} ${op.toLowerCase()}`;
    if (op === "Između") return `${side(c.levo)} između ${side(c.vrednost)} i ${side(c.do)}`;
    return `${side(c.levo)} ${OPERATOR_SIGNS[op] ?? op.toLowerCase()} ${side(c.vrednost)}`;
  });
  return parts.join(String(params.combine || "").startsWith("Dovoljna") ? " ili " : " i ");
}

/** Whether a param's field is shown: some only apply when another param has a certain value. */
function isShown(spec: ParamSpec, type: TaskType, task: Task): boolean {
  if (!spec.show_if) return true;
  const [name, wanted] = spec.show_if;
  const other = type.params.find((p) => p.name === name);
  return (task.params[name] || other?.default || "") === wanted;
}

/** What is known about the page an "Otvori stranicu" task opens. */
function PageFacts({ path, info }: { path: string; info: PageInfo | undefined }) {
  if (!info) {
    return (
      <p className="muted small page-facts">
        Polja ove stranice još nisu poznata. Biće zapamćena posle prvog pokretanja.
      </p>
    );
  }
  return (
    <div className="page-facts small">
      <div>
        <strong>{info.naslov || path}</strong>
        <span className="muted"> · {info.filter ? "ima polje „Filter…“" : "nema polje za pretragu"}</span>
        {info.izvor && <span className="muted"> · izvor: {info.izvor}</span>}
      </div>
      {info.tabele.map((t) => (
        <div key={t.id}>
          <span className="muted">Tabela {t.naziv ? `„${t.naziv}“` : t.id}:</span>{" "}
          {t.kolone.map((c) => (
            <span key={c} className="chip">
              {c}
            </span>
          ))}
        </div>
      ))}
    </div>
  );
}

/** The task types as options, under their groups (TiM ERP, Tok posla, PURS, ...). */
export function TypeOptions({ types, soon }: { types: TaskType[]; soon?: boolean }) {
  const groups: Record<string, TaskType[]> = {};
  for (const t of types) (groups[t.group || "Ostalo"] ??= []).push(t);
  return (
    <>
      {Object.entries(groups).map(([group, list]) => (
        <optgroup key={group} label={group}>
          {list.map((t) => (
            <option key={t.id} value={t.id}>
              {t.title}
              {soon && !t.implemented ? " (uskoro)" : ""}
            </option>
          ))}
        </optgroup>
      ))}
    </>
  );
}

/** A number as typed in a number field: optional sign, digits with "." or " " between thousands, "," or "." decimals. */
const NUMBER_TEXT = /^[-+]?\s*(\d{1,3}([. ]\d{3})+|\d+)([.,]\d+)?$/;

type FieldProps = {
  spec: ParamSpec;
  value: ParamValue;
  sources: Source[];
  pageColumns: string[];
  pageBefore: string | undefined;
  jumpTargets: Sibling[];
  filterFields: FilterField[];
  params?: Record<string, ParamValue>; // the task's other params (a "choice" depends on one of them)
  onChange: (v: ParamValue) => void;
};

function ParamField({ spec, value, sources, pageColumns, pageBefore, jumpTargets, filterFields, params, onChange }: FieldProps) {
  const canRef = spec.allow_ref && sources.length > 0;
  const caret = useRef<HTMLInputElement | HTMLTextAreaElement | null>(null);
  // Fields that can hold "$2.1.Dokument$" tokens (filled in when the task runs).
  const tokens = ["text", "textarea", "date", "number"].includes(spec.kind) && spec.allow_ref && sources.length > 0;
  const fromTask = isRef(value);
  const text = typeof value === "string" ? value : "";
  const rowSource = sources.find((s) => s.kind === "row");
  const listId = useId();

  let input;
  if (spec.kind === "dataset") {
    const chosen = isRef(value) ? sources.find((s) => s.id === value.ref && s.kind !== "row") : undefined;
    const options = sources.filter((s) => s.kind !== "row");
    input = options.length ? (
      <>
        <select
          value={chosen?.id ?? ""}
          onChange={(e) => onChange(e.target.value ? { ref: e.target.value, pick: "value", column: "" } : "")}
        >
          <option value="">— izaberite zadatak —</option>
          {options.map((s) => (
            <option key={s.id} value={s.id}>
              #{s.number} {s.title}
            </option>
          ))}
        </select>
        {isRef(value) && !chosen && <span className="error small">Izabrani zadatak više nije pre ove petlje; izaberite drugi.</span>}
        {chosen && (
          <span className="muted small">
            {chosen.columns.length
              ? `Kolone u „Trenutnom redu“: ${chosen.columns.join(", ")}.`
              : "Kolone će biti poznate posle prvog pokretanja."}
          </span>
        )}
      </>
    ) : (
      <span className="error small">Pre petlje nema zadatka sa redovima; dodajte npr. „Pretragu“.</span>
    );
  } else if (fromTask) {
    input = <RefEditor value={value} sources={sources} onChange={onChange} expect={spec.kind} />;
  } else if (spec.kind === "bool") {
    input = (
      <span className="inline bool-field">
        <Check checked={value === true} onChange={onChange}>
          <span className="small">{value === true ? "Da" : "Ne"}</span>
        </Check>
      </span>
    );
  } else if (spec.kind === "conditions") {
    input = (
      <ConditionsEditor
        value={Array.isArray(value) ? (value as CheckValue[]) : []}
        operators={spec.options}
        sources={sources}
        onChange={onChange}
      />
    );
  } else if (spec.kind === "task") {
    const missing = !!text && !jumpTargets.some((s) => s.id === text);
    input = jumpTargets.length ? (
      <>
        <select value={missing ? "" : text} onChange={(e) => onChange(e.target.value)}>
          <option value="">— izaberite zadatak —</option>
          {jumpTargets.map((s) => (
            <option key={s.id} value={s.id}>
              #{s.number} {s.title}
            </option>
          ))}
        </select>
        {missing && <span className="error small">Izabrani zadatak više nije posle ovog; izaberite drugi.</span>}
      </>
    ) : (
      <span className="error small">Posle ovog nema zadatka na koji se može skočiti (u istom redu).</span>
    );
  } else if (spec.kind === "filters") {
    input = (
      <FiltersEditor
        value={Array.isArray(value) ? (value as FilterValue[]) : []}
        fields={filterFields}
        local={!!spec.fields?.length}
        pageBefore={pageBefore}
        sources={sources}
        onChange={onChange}
      />
    );
  } else if (spec.kind === "menu") {
    const groups: Record<string, string[]> = {};
    for (const path of spec.options) (groups[path.split(" > ")[0]] ??= []).push(path);
    input = (
      <select value={text} onChange={(e) => onChange(e.target.value)}>
        <option value="">— izaberite —</option>
        {Object.entries(groups).map(([group, paths]) => (
          <optgroup key={group} label={group}>
            {paths.map((path) => (
              <option key={path} value={path}>
                {path.replace(" > ", " › ")}
              </option>
            ))}
          </optgroup>
        ))}
      </select>
    );
  } else if (spec.kind === "select") {
    input = (
      <select value={text || spec.default} onChange={(e) => onChange(e.target.value)}>
        {!spec.default && <option value="">— izaberite —</option>}
        {spec.options.map((o) => (
          <option key={o}>{o}</option>
        ))}
      </select>
    );
  } else if (spec.kind === "secret") {
    const saved = isSecret(value) && !!value.secret;
    const typed = isSecret(value) ? value.value ?? "" : "";
    input = (
      <span className="inline secret-field">
        <input
          type="password"
          autoComplete="new-password"
          value={typed}
          placeholder={saved ? "novi, za promenu" : "nije upisan"}
          onChange={(e) =>
            onChange(e.target.value ? { secret: saved ? value.secret : "", value: e.target.value } : saved ? { secret: value.secret } : "")
          }
        />
        {saved && !typed && <span className="badge">sačuvan</span>}
        {(saved || typed) && (
          <button type="button" className="link" onClick={() => onChange("")}>
            Obriši
          </button>
        )}
      </span>
    );
  } else if (spec.kind === "choice") {
    input = <ChoiceField spec={spec} value={text} depends={params?.[spec.depends ?? ""]} onChange={onChange} />;
  } else if (spec.kind === "date" && !text.includes("$")) {
    input = <DateInput value={text} onChange={onChange} />;
  } else if (spec.kind === "textarea") {
    input = <textarea ref={(el) => { caret.current = el; }} rows={3} value={text} onChange={(e) => onChange(e.target.value)} />;
  } else if (spec.kind === "column") {
    input = (
      <>
        <input list={listId} value={text} placeholder="sve kolone" onChange={(e) => onChange(e.target.value)} />
        <datalist id={listId}>
          {pageColumns.map((c) => (
            <option key={c} value={c} />
          ))}
        </datalist>
      </>
    );
  } else if (spec.kind === "number") {
    // Text, not type="number": it takes a sign, "1.234,56" and tokens like -$3.1.ukupno.Virman$.
    const bad = !!text.trim() && !text.includes("$") && !NUMBER_TEXT.test(text.trim());
    input = (
      <>
        <input
          ref={(el) => { caret.current = el; }}
          className={`number-input${bad ? " invalid" : ""}`}
          inputMode="decimal"
          value={text}
          placeholder="npr. 1234,56 ili -1234,56"
          onChange={(e) => onChange(e.target.value)}
        />
        {bad && <span className="error small">„{text}“ nije broj.</span>}
      </>
    );
  } else {
    input = (
      <input
        ref={(el) => { caret.current = el; }}
        type="text"
        value={text}
        placeholder={rowSource && spec.row_column ? `prazno = ${spec.row_column} iz trenutnog reda` : undefined}
        onChange={(e) => onChange(e.target.value)}
      />
    );
  }

  let hint = spec.help;
  if (!fromTask && spec.kind === "column") {
    hint = pageBefore
      ? pageColumns.length
        ? `${spec.help} Kolone stranice „${pageBefore}“: ${pageColumns.join(", ")}.`
        : `${spec.help} Kolone stranice „${pageBefore}“ biće poznate posle prvog pokretanja.`
      : `${spec.help} Dodajte zadatak „Otvori stranicu“ pre ovog.`;
  }

  return (
    <label className={fromTask || spec.kind === "filters" || spec.kind === "conditions" ? "wide" : ""}>
      <span className="field-label">
        {spec.label}
        {spec.required && <span className="required"> *</span>}
        {canRef && (
          <span className="mini-toggle" role="radiogroup" aria-label={`Izvor za ${spec.label}`}>
            <button
              type="button"
              role="radio"
              aria-checked={!fromTask}
              className={fromTask ? "" : "on"}
              onClick={() => fromTask && onChange(spec.default)}
            >
              Unos
            </button>
            <button
              type="button"
              role="radio"
              aria-checked={fromTask}
              className={fromTask ? "on" : ""}
              onClick={() => {
                if (fromTask) return;
                if (rowSource) {
                  const column = spec.row_column || (rowSource.columns.includes("Dokument") ? "Dokument" : rowSource.columns[0] ?? "");
                  onChange({ ref: ROW, pick: "current", column });
                  return;
                }
                const last = sources[sources.length - 1];
                onChange({ ref: last.id, pick: "first", column: last.columns.includes("Naziv") ? "Naziv" : (last.columns[0] ?? "") });
              }}
            >
              Iz zadatka
            </button>
          </span>
        )}
      </span>
      {input}
      {tokens && !isRef(value) && (
        <TokenTools
          text={typeof value === "string" ? value : ""}
          sources={sources}
          expect={spec.kind}
          onInsert={(token) => {
            const current = typeof value === "string" ? value : "";
            const el = caret.current;
            const at = el && document.activeElement !== null && el.selectionStart !== null ? el.selectionStart : current.length;
            onChange(spec.kind === "date" ? token : current.slice(0, at) + token + current.slice(at));
          }}
        />
      )}
      {hint && <span className="muted small">{hint}</span>}
    </label>
  );
}

/** The advanced filters of a "Pretraga" task: field, operator, value(s). */
function FiltersEditor(props: {
  value: FilterValue[];
  fields: FilterField[];
  local?: boolean; // conditions checked by the program (a list of values is allowed), not the site's filters
  pageBefore: string | undefined;
  sources: Source[];
  onChange: (v: FilterValue[]) => void;
}) {
  const { value, fields, sources, onChange } = props;
  const unused = fields.filter((f) => !value.some((v) => v.polje === f.id));
  const [adding, setAdding] = useState("");

  if (!fields.length) {
    return (
      <p className="muted small">
        {props.pageBefore
          ? `Filteri stranice „${props.pageBefore}“ još nisu poznati.`
          : "Dodajte zadatak „Otvori stranicu“ pre ovog (npr. Maloprodaja › Izlazi)."}
      </p>
    );
  }

  function update(i: number, patch: Partial<FilterValue>) {
    onChange(value.map((v, j) => (j === i ? { ...v, ...patch } : v)));
  }

  function add(id: string) {
    const field = fields.find((f) => f.id === id);
    if (!field) return;
    const operator = field.vrsta === "text" && field.operatori.includes("Sadrži") ? "Sadrži" : field.operatori[0];
    const first: FilterValue = { polje: id, operator };
    if (field.vrsta === "list") first.izbor = [];
    if (field.vrsta === "bool") first.vrednost = "Da";
    onChange([...value, first]);
    setAdding("");
  }

  return (
    <div className="filters">
      {value.length === 0 && <p className="muted small">{props.local ? "Nema uslova: vraćaju se svi redovi." : "Nijedan filter nije izabran."}</p>}
      {value.map((f, i) => {
        const field = fields.find((x) => x.id === f.polje);
        if (!field) {
          return (
            <div key={i} className="filter-row">
              <span className="error small">Nepoznat filter „{f.polje}“</span>
              <button className="icon" onClick={() => onChange(value.filter((_, j) => j !== i))} aria-label="Ukloni filter">
                ✕
              </button>
            </div>
          );
        }
        return (
          <div key={f.polje} className="filter-row">
            <span className="filter-name">{field.naziv}</span>
            <select value={f.operator} onChange={(e) => update(i, { operator: e.target.value })} aria-label="Operator">
              {field.operatori.map((o) => (
                <option key={o}>{o}</option>
              ))}
            </select>
            {field.vrsta === "list" ? (
              <span className="filter-choices">
                {(field.opcije ?? []).map((o) => (
                  <Check
                    key={o}
                    className="small"
                    checked={(f.izbor ?? []).includes(o)}
                    onChange={(c) => update(i, { izbor: c ? [...(f.izbor ?? []), o] : (f.izbor ?? []).filter((x) => x !== o) })}
                  >
                    {o}
                  </Check>
                ))}
              </span>
            ) : field.vrsta === "bool" ? (
              <select value={typeof f.vrednost === "string" ? f.vrednost : "Da"} onChange={(e) => update(i, { vrednost: e.target.value })}>
                {(field.opcije ?? ["Ne", "Da"]).map((o) => (
                  <option key={o}>{o}</option>
                ))}
              </select>
            ) : (
              <>
                <ValueInput
                  value={f.vrednost ?? ""}
                  placeholder={field.vrsta === "date" ? "DD/MM/YYYY" : field.vrsta === "number" ? "broj" : "vrednost"}
                  sources={sources}
                  inCondition={props.local}
                  onChange={(v) => update(i, { vrednost: v })}
                />
                {f.operator === "Između" && (
                  <>
                    <span className="muted small">do</span>
                    <ValueInput
                      value={f.do ?? ""}
                      placeholder={field.vrsta === "date" ? "DD/MM/YYYY" : "do"}
                      sources={sources}
                      inCondition={props.local}
                      onChange={(v) => update(i, { do: v })}
                    />
                  </>
                )}
              </>
            )}
            <button className="icon" onClick={() => onChange(value.filter((_, j) => j !== i))} aria-label="Ukloni filter" title="Ukloni filter">
              ✕
            </button>
          </div>
        );
      })}
      {unused.length > 0 && (
        <div className="add-task">
          <select value={adding} onChange={(e) => setAdding(e.target.value)} aria-label="Novi filter">
            <option value="">— izaberite polje —</option>
            {unused.map((f) => (
              <option key={f.id} value={f.id}>
                {f.naziv}
              </option>
            ))}
          </select>
          <button disabled={!adding} onClick={() => add(adding)}>
            {props.local ? "+ Dodaj uslov" : "+ Dodaj filter"}
          </button>
        </div>
      )}
    </div>
  );
}

/** A typed value, or (with "Iz zadatka") one taken from an earlier task / the current row. */
function ValueInput(props: {
  value: string | ParamRef;
  placeholder: string;
  sources: Source[];
  inCondition?: boolean;
  onChange: (v: string | ParamRef) => void;
}) {
  const { value, sources, onChange } = props;
  if (typeof value !== "string") {
    return (
      <span className="value-ref">
        <RefEditor value={value} sources={sources} onChange={onChange} inCondition={props.inCondition} />
        <button className="icon" title="Upiši vrednost" onClick={() => onChange("")}>
          ✎
        </button>
      </span>
    );
  }
  const row = sources.find((s) => s.kind === "row");
  const fallback = sources[sources.length - 1];
  return (
    <span className="value-input">
      <input value={value} placeholder={props.placeholder} onChange={(e) => onChange(e.target.value)} />
      {sources.length > 0 && (
        <button
          className="icon"
          title="Vrednost iz zadatka / trenutnog reda"
          onClick={() =>
            onChange(
              row
                ? { ref: row.id, pick: "current", column: row.columns[0] ?? "" }
                : { ref: fallback.id, pick: "first", column: fallback.columns[0] ?? "" },
            )
          }
        >
          ⇢
        </button>
      )}
    </span>
  );
}

const PICKS: [ParamRef["pick"], string][] = [
  ["first", "Prvi red"],
  ["row", "Red broj…"],
  ["all", "Svaki red (zadatak se pokreće za svaki)"],
  ["count", "Broj redova"],
  ["total", "Ukupan iznos"],
  ["value", "Cela vrednost"],
];

function RefEditor(props: { value: ParamRef; sources: Source[]; onChange: (v: ParamRef) => void; inCondition?: boolean; expect?: string }) {
  const { value, sources, onChange, inCondition } = props;
  const kinds = useContext(KindsContext);
  const source = sources.find((s) => s.id === value.ref);
  const isRow = source?.kind === "row";
  const picks: [ParamRef["pick"], string][] = isRow
    ? []
    : [
        ...(source?.current ? [["current", "Trenutni red petlje"] as [ParamRef["pick"], string]] : []),
        ...PICKS.filter(([pick]) => pick !== "total" || source?.totals.length),
      ];
  const needsColumn = isRow || ["first", "row", "all", "total", "current"].includes(value.pick);
  const kindWarning = needsColumn || value.pick === "count"
    ? kindProblem(
        value.pick === "total" ? `Ukupan iznos „${value.column}“` : value.pick === "count" ? "Broj redova" : `Kolona „${value.column}“`,
        value.column || value.pick === "count" ? refKind(kinds, source, value.pick, value.column ?? "") : undefined,
        props.expect,
      )
    : "";
  const options = value.pick === "total" ? (source?.totals ?? []) : (source?.columns ?? []);
  // Known columns of the chosen task: only those can be picked (unknown ones, e.g. before a page was seen, are typed).
  const strict = options.length > 0;
  const missing = needsColumn && strict && !!value.column && !options.includes(value.column);

  function changeSource(id: string) {
    const next = sources.find((s) => s.id === id);
    // Inside a loop over that task's rows the current row is what is usually wanted.
    const pick = next?.kind === "row" || next?.current ? "current" : value.pick === "current" ? "first" : value.pick;
    // A column of the previous source is kept only if the new one has it too.
    const known = pick === "total" ? (next?.totals ?? []) : (next?.columns ?? []);
    const column = value.column && known.length && !known.includes(value.column) ? "" : value.column;
    onChange({ ...value, ref: id, pick, column });
  }

  return (
    <div className="ref-editor">
      <select value={source ? value.ref : ""} onChange={(e) => changeSource(e.target.value)} aria-label="Izvor">
        {!source && <option value="">— izvor više nije dostupan —</option>}
        {sources.map((s) => (
          <option key={s.id} value={s.id}>
            {s.kind === "row" ? s.title : `#${s.number} ${s.title}`}
          </option>
        ))}
      </select>
      {!isRow && (
        <select value={value.pick} onChange={(e) => onChange({ ...value, pick: e.target.value as ParamRef["pick"] })} aria-label="Šta uzeti">
          {picks.map(([pick, label]) => (
            <option key={pick} value={pick}>
              {inCondition && pick === "all" ? "Svi redovi (važi ako odgovara bilo koji)" : label}
            </option>
          ))}
        </select>
      )}
      {value.pick === "row" && !isRow && (
        <input
          type="number"
          min={1}
          className="row-no"
          value={value.row ?? 1}
          onChange={(e) => onChange({ ...value, row: Number(e.target.value) || 1 })}
          aria-label="Broj reda"
        />
      )}
      {needsColumn && (
        <NameSelect
          value={value.column ?? ""}
          options={options}
          placeholder={value.pick === "total" ? "iznos (npr. Ukupno)" : "kolona"}
          onChange={(column) => onChange({ ...value, column })}
          ariaLabel="Kolona"
          strict={strict}
        />
      )}
      {!source && <span className="error small">Izaberite neki od ponuđenih izvora.</span>}
      {kindWarning && !missing && <span className="error small">{kindWarning}</span>}
      {missing && source && (
        <span className="error small">
          Zadatak #{source.number} nema {value.pick === "total" ? "iznos" : "kolonu"} „{value.column}“. Ima: {options.join(", ")}.
        </span>
      )}
    </div>
  );
}

type OpenedPage = PageInfo & { stranica: string; tabele: (PageInfo["tabele"][number] & { ukupno?: number })[] };

type Rows = {
  kolone?: string[];
  redovi: Record<string, string>[]; // only the first rows (a preview); all of them are in the files
  broj?: number; // all rows
  ukupno_na_stranici?: number;
  skraceno?: boolean;
  pokretanja?: number;
  napomena?: string;
  fajl?: string; // data/results/<fajl>.csv|json with every row
  ukupno?: Record<string, string>; // totals, e.g. Fiskalni računi: {Kartica: "1.798,59", ...}
  zbir_odgovara?: boolean; // the totals equal the sums of the rows
  razlike?: string[];
};

const MAX_SHOWN = 25;

function TaskResultView({ result }: { result: TaskResult }) {
  const [showJson, setShowJson] = useState(false);
  const value = result.value as Record<string, unknown> | null;
  const hasValue = value !== null && value !== undefined;
  const rows = hasValue && Array.isArray((value as Rows).redovi) ? (value as Rows) : null;
  const total = rows ? (rows.broj ?? rows.redovi.length) : 0;
  // "Ulaz u stavke" / "Finansijski nalog" (opened a page) and "Nazad", once or once per row.
  const runs = (Array.isArray(value) ? value : value ? [value] : []) as Record<string, unknown>[];
  const navigation =
    runs.length && runs.every((v) => v && typeof v === "object" && ("otvoreno" in v || "na" in v)) && !rows
      ? "otvoreno" in runs[0]
        ? `Otvorena stranica „${runs[0].otvoreno}“${runs.length > 1 ? ` · ${runs.length}×` : ""}`
        : `Povratak: ${runs[0].sa} → ${runs[0].na}${runs.length > 1 ? ` · ${runs.length}×` : ""}`
      : "";
  const page = hasValue && Array.isArray((value as { tabele?: unknown }).tabele) ? (value as unknown as OpenedPage) : null;

  return (
    <div className="task-result">
      <div className="task-result-head">
        <span className="muted small">Poslednje pokretanje:</span>
        <StatusBadge status={result.status} />
        {result.started_at && <span className="muted small">{formatDuration(result.started_at, result.finished_at)}</span>}
        {result.status === "running" && result.progress && <span className="small progress-text">{result.progress}</span>}
        {rows && (
          <span className="small">
            <strong>{total}</strong> {total === 1 ? "red" : "redova"}
            {rows.ukupno_na_stranici !== undefined && <span className="muted"> (na stranici posle pretrage: {rows.ukupno_na_stranici})</span>}
            {rows.pokretanja !== undefined && <span className="muted"> · pokrenut {rows.pokretanja}×</span>}
            {rows.skraceno && <span className="warning"> · skraćeno na zadati broj redova</span>}
          </span>
        )}
        {rows?.fajl && (
          <span className="small downloads">
            Preuzmi sve: <a href={`/files/results/${rows.fajl}.csv`}>CSV (Excel)</a> ·{" "}
            <a href={`/files/results/${rows.fajl}.json`}>JSON</a>
          </span>
        )}
        {hasValue && (
          <button className="link small" onClick={() => setShowJson(!showJson)}>
            {showJson ? "Sakrij detalje" : "Detalji"}
          </button>
        )}
      </div>
      {result.error && <pre className="error-box">{result.error}</pre>}
      {result.napomena && <p className="small warning note">{result.napomena}</p>}
      {result.status === "done" && hasValue && typeof (value as { postoji?: unknown }).postoji === "boolean" && !showJson && (
        <OrderCheck value={value as { postoji: boolean; nalog: string; povezano?: Record<string, string> }} />
      )}
      {(result.errors?.length ?? 0) > 1 && (
        <details className="small row-errors">
          <summary>Sve greške ({result.errors!.length})</summary>
          <ul>
            {result.errors!.map((e) => (
              <li key={e}>{e}</li>
            ))}
          </ul>
        </details>
      )}
      {rows?.ukupno && Object.keys(rows.ukupno).length > 0 && !showJson && <Totals rows={rows} />}
      {result.status === "done" && !hasValue && <span className="muted small">Zadatak nije vratio vrednost.</span>}
      {showJson ? (
        <CodeBlock className="value-box" value={result.value} />
      ) : rows ? (
        rows.napomena ? (
          <p className="muted small">{rows.napomena}</p>
        ) : (
          rows.redovi.length > 0 &&
          !(typeof (value as { postoji?: unknown })?.postoji === "boolean") && <RowsTable rows={rows} total={total} />
        )
      ) : navigation ? (
        <p className="small page-opened">{navigation}</p>
      ) : page ? (
        <p className="small page-opened">
          Otvorena stranica <strong>{page.naslov}</strong> · {page.tabele.length}{" "}
          {page.tabele.length === 1 ? "tabela" : "tabele"}
          {page.tabele[0] && <span className="muted"> (glavna: {page.tabele[0].ukupno ?? "?"} redova)</span>}
        </p>
      ) : (
        hasValue && <CodeBlock className="value-box" value={result.value} />
      )}
    </div>
  );
}

/** Table preview of a task's value, as under a task on the job page (rows, totals, an order check). False if
 * the value has nothing to show as a table. */
export function ValuePreview({ value }: { value: unknown }) {
  if (!value || typeof value !== "object" || Array.isArray(value)) return null;
  const v = value as Record<string, unknown>;
  if (typeof v.postoji === "boolean") return <OrderCheck value={v as { postoji: boolean; nalog: string; povezano?: Record<string, string> }} />;
  if (!Array.isArray(v.redovi)) {
    return v.ukupno && typeof v.ukupno === "object" ? <Totals rows={{ redovi: [], ukupno: v.ukupno as Record<string, string> }} /> : null;
  }
  const rows = v as unknown as Rows;
  const total = rows.broj ?? rows.redovi.length;
  return (
    <div className="value-preview">
      <span className="small">
        <strong>{total}</strong> {total === 1 ? "red" : "redova"}
        {rows.fajl && (
          <span className="downloads">
            {" "}· Preuzmi sve: <a href={`/files/results/${rows.fajl}.csv`}>CSV (Excel)</a> ·{" "}
            <a href={`/files/results/${rows.fajl}.json`}>JSON</a>
          </span>
        )}
      </span>
      {rows.ukupno && Object.keys(rows.ukupno).length > 0 && <Totals rows={rows} />}
      {rows.napomena ? <p className="muted small">{rows.napomena}</p> : rows.redovi.length > 0 && <RowsTable rows={rows} total={total} />}
    </div>
  );
}

/** Result of a check like "Finansijski nalog": exists or not, plus the document's other links. */
function OrderCheck({ value }: { value: { postoji: boolean; nalog: string; povezano?: Record<string, string> } }) {
  return (
    <div className="totals small">
      <span className={value.postoji ? "check ok" : "check bad"} style={{ marginLeft: 0 }}>
        {value.postoji ? `✓ Finansijski nalog postoji: ${value.nalog}` : "✗ Finansijski nalog ne postoji"}
      </span>
      {Object.entries(value.povezano ?? {})
        .filter(([k]) => k !== "Finansijski nalog")
        .map(([k, v]) => (
          <span key={k} className="total">
            {k} <strong>{v}</strong>
          </span>
        ))}
    </div>
  );
}

function Totals({ rows }: { rows: Rows }) {
  return (
    <div className="totals small">
      <span className="muted">{rows.pokretanja ? `Ukupno (${rows.pokretanja} pokretanja):` : "Ukupno:"}</span>
      {Object.entries(rows.ukupno ?? {}).map(([name, value]) => (
        <span key={name} className={`total ${name === "Ukupno" ? "grand" : ""}`}>
          {name} <strong>{value}</strong>
        </span>
      ))}
      {rows.zbir_odgovara !== undefined && (
        <span className={rows.zbir_odgovara ? "check ok" : "check bad"} title={(rows.razlike ?? []).join("\n")}>
          {rows.zbir_odgovara ? "✓ zbir redova odgovara" : "⚠ zbir redova ne odgovara"}
        </span>
      )}
    </div>
  );
}

function RowsTable({ rows, total }: { rows: Rows; total: number }) {
  const columns = rows.kolone?.length ? rows.kolone : Object.keys(rows.redovi[0] ?? {});
  return (
    <div className="rows-wrap">
      <table className="rows">
        <thead>
          <tr>
            <th className="num">#</th>
            {columns.map((c) => (
              <th key={c}>{c}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.redovi.slice(0, MAX_SHOWN).map((row, i) => (
            <tr key={i}>
              <td className="num muted">{i + 1}</td>
              {columns.map((c) => (
                <td key={c}>{row[c]}</td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
      {total > Math.min(rows.redovi.length, MAX_SHOWN) && (
        <p className="muted small table-note">
          Prikazano prvih {Math.min(rows.redovi.length, MAX_SHOWN)} od {total} redova. Svi redovi su u fajlu za
          preuzimanje i dostupni su sledećim zadacima.
        </p>
      )}
    </div>
  );
}

/** A window over the page for editing a subtask; its header shows which tasks it belongs to. Escape or
 * a click on the backdrop closes it (only the topmost one when windows are stacked for deeper subtasks). */
function Modal(props: { id: string; trail: Crumb[]; number: string; title: string; onClose: () => void; children: ReactNode }) {
  const ref = useRef<HTMLDivElement>(null);
  const onCloseRef = useRef(props.onClose);
  onCloseRef.current = props.onClose;

  useEffect(() => {
    const isTop = () => {
      const all = document.querySelectorAll(".modal-backdrop");
      return all[all.length - 1] === ref.current;
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape" && isTop()) onCloseRef.current();
    };
    window.addEventListener("keydown", onKey);
    ref.current?.querySelector<HTMLElement>(".modal")?.focus();
    document.body.classList.add("modal-open");
    return () => {
      window.removeEventListener("keydown", onKey);
      if (document.querySelectorAll(".modal-backdrop").length <= 1) document.body.classList.remove("modal-open");
    };
  }, []);

  return createPortal(
    <div
      ref={ref}
      className="modal-backdrop"
      // Each deeper window sits a little lower, so the stack of open windows stays visible.
      style={{ paddingTop: 32 + 28 * (props.trail.length - 1) }}
      onMouseDown={(e) => e.target === e.currentTarget && props.onClose()}>
      <div className="modal" role="dialog" aria-modal="true" aria-label={`Podzadatak ${props.number}`} tabIndex={-1}>
        <div className="modal-head">
          <nav className="crumbs" aria-label="Pripada zadatku">
            {props.trail.map((c) => (
              <span key={c.number} className="crumb">
                <span className="task-no">{c.number}</span> {c.title}
                <span className="crumb-sep">›</span>
              </span>
            ))}
            <span className="crumb current">
              <span className="task-no">{props.number}</span> {props.title}
            </span>
          </nav>
          <button className="icon" onClick={props.onClose} aria-label="Zatvori" title="Zatvori (Esc)">
            ✕
          </button>
        </div>
        <LeaveZones levels={[...props.trail, { id: props.id, number: props.number, title: props.title }]} />
        <div className="modal-body">{props.children}</div>
        <div className="modal-foot">
          <span className="muted small">Izmene se čuvaju dugmetom „Sačuvaj“ na stranici posla.</span>
          <button className="primary" onClick={props.onClose}>
            Gotovo
          </button>
        </div>
      </div>
    </div>,
    document.body,
  );
}

const CHECK_KINDS = ["Automatski", "Tekst", "Broj", "Datum"];
const NO_VALUE = ["Je prazno", "Nije prazno"];

/** The checks of a "Uslov" task: value from an earlier task, how to compare, operator, value(s). */
function ConditionsEditor(props: {
  value: CheckValue[];
  operators: string[];
  sources: Source[];
  onChange: (v: CheckValue[]) => void;
}) {
  const { value, operators, sources, onChange } = props;
  if (!sources.length) {
    return <p className="muted small">Uslov proverava rezultate ranijih zadataka; dodajte zadatak pre ovog.</p>;
  }

  function update(i: number, patch: Partial<CheckValue>) {
    onChange(value.map((v, j) => (j === i ? { ...v, ...patch } : v)));
  }

  function add() {
    const row = sources.find((s) => s.kind === "row");
    const last = row ?? sources[sources.length - 1];
    const left: ParamRef = row
      ? { ref: row.id, pick: "current", column: row.columns[0] ?? "" }
      : { ref: last.id, pick: "first", column: last.columns[0] ?? "" };
    onChange([...value, { levo: left, operator: "Jednako", vrednost: "", vrsta: "Automatski" }]);
  }

  return (
    <div className="filters checks">
      {value.length === 0 && <p className="muted small">Nema provera.</p>}
      {value.map((c, i) => (
        <div key={i} className="check-row">
          <span className="check-no">{i + 1}.</span>
          <span className="check-left">
            {typeof c.levo === "string" ? (
              <span className="error small">Izaberite vrednost iz zadatka.</span>
            ) : (
              <RefEditor value={c.levo} sources={sources} inCondition onChange={(v) => update(i, { levo: v })} />
            )}
          </span>
          <span className="check-right">
            <select value={c.vrsta || "Automatski"} onChange={(e) => update(i, { vrsta: e.target.value })} aria-label="Poredi kao" title="Poredi kao">
              {CHECK_KINDS.map((k) => (
                <option key={k}>{k}</option>
              ))}
            </select>
            <select value={c.operator} onChange={(e) => update(i, { operator: e.target.value })} aria-label="Operator">
              {operators.map((o) => (
                <option key={o}>{o}</option>
              ))}
            </select>
            {!NO_VALUE.includes(c.operator) && (
              <ValueInput
                value={c.vrednost ?? ""}
                placeholder="vrednost"
                sources={sources}
                inCondition
                onChange={(v) => update(i, { vrednost: v })}
              />
            )}
            {c.operator === "Između" && (
              <>
                <span className="muted small">i</span>
                <ValueInput value={c.do ?? ""} placeholder="do" sources={sources} inCondition onChange={(v) => update(i, { do: v })} />
              </>
            )}
            <button className="icon" onClick={() => onChange(value.filter((_, j) => j !== i))} aria-label="Ukloni proveru" title="Ukloni proveru">
              ✕
            </button>
          </span>
        </div>
      ))}
      <div className="add-task">
        <button onClick={add}>+ Dodaj proveru</button>
      </div>
    </div>
  );
}

/** Whether this task or one of its subtasks is being computed right now. */
function hasActive(result: TaskResult | undefined): boolean {
  return !!result && (!!result.aktivan || (result.subtasks ?? []).some(hasActive));
}

/** Drop handling on a task: the upper part puts the dragged task before it, the lower part after it, and
 * the middle (or, on a card's head, the lower half) into it when it can hold tasks. */
function useDropOn(id: string, holds: boolean, shape: "row" | "head") {
  const drag = useDrag();
  const [where, setWhere] = useState<"before" | "after" | "into" | null>(null);
  useEffect(() => {
    if (!drag?.dragging) setWhere(null);
  }, [drag?.dragging]);

  function targetAt(e: React.DragEvent<HTMLElement>): DropTarget | null {
    if (!drag?.dragging) return null;
    const box = e.currentTarget.getBoundingClientRect();
    const y = (e.clientY - box.top) / Math.max(box.height, 1);
    const side = y < 0.5 ? "before" : "after";
    let kinds: ("before" | "after" | "into")[];
    if (shape === "head") kinds = y < 0.5 ? ["before"] : holds ? ["into", "after"] : ["after"];
    else if (y < 0.3 || y > 0.7) kinds = [side];
    else kinds = holds ? ["into", side] : [side];
    for (const kind of kinds) {
      const target: DropTarget = { kind, id };
      if (!drag.blocker(target)) return target;
    }
    return null;
  }

  const handlers = {
    onDragOver: (e: React.DragEvent<HTMLElement>) => {
      const target = targetAt(e);
      if (!target || target.kind === "end") return setWhere(null);
      e.preventDefault();
      e.stopPropagation();
      e.dataTransfer.dropEffect = "move";
      setWhere(target.kind);
    },
    onDragLeave: (e: React.DragEvent<HTMLElement>) => {
      if (!e.currentTarget.contains(e.relatedTarget as Node | null)) setWhere(null);
    },
    onDrop: (e: React.DragEvent<HTMLElement>) => {
      const target = targetAt(e);
      setWhere(null);
      if (!target) return;
      e.preventDefault();
      e.stopPropagation();
      drag!.drop(target);
    },
  };
  return { handlers, className: where ? `drop-${where}` : "" };
}

/** Grip to drag a task card (its head has inputs, so the whole head isn't draggable). */
function DragHandle({ id }: { id: string }) {
  const drag = useDrag();
  if (!drag) return null;
  return (
    <span
      className="drag-handle"
      draggable
      title="Prevucite da premestite zadatak (na drugi zadatak da postane njegov podzadatak)"
      onDragStart={(e) => {
        e.stopPropagation();
        e.dataTransfer.effectAllowed = "move";
        e.dataTransfer.setData("text/plain", id);
        const card = e.currentTarget.closest("li");
        if (card) e.dataTransfer.setDragImage(card, 20, 20);
        drag.start(id);
      }}
      onDragEnd={drag.end}
    >
      ⠿
    </span>
  );
}

/** A subtask's line: the whole line can be dragged, and tasks can be dropped on it. */
function SubtaskRow(props: { id: string; holds: boolean; className: string; children: ReactNode }) {
  const drag = useDrag();
  const drop = useDropOn(props.id, props.holds, "row");
  return (
    <div
      className={`subtask-row ${props.className} ${drop.className} ${drag?.dragging === props.id ? "is-dragged" : ""}`}
      draggable={!!drag}
      title={drag ? "Prevucite da premestite zadatak (na drugi zadatak da postane njegov podzadatak)" : undefined}
      onDragStart={(e) => {
        e.stopPropagation();
        e.dataTransfer.effectAllowed = "move";
        e.dataTransfer.setData("text/plain", props.id);
        drag?.start(props.id);
      }}
      onDragEnd={drag?.end}
      {...drop.handlers}
    >
      {drag && (
        <span className="drag-handle" aria-hidden>
          ⠿
        </span>
      )}
      {props.children}
    </div>
  );
}

/** "⤴" on a subtask's line: takes it out of the list it is in, right after the task that list belongs to (one level up),
 * without dragging (e.g. from a subtask's window to the list behind it). */
function MoveOut({ id, owner }: { id: string; owner: Crumb | undefined }) {
  const drag = useDrag();
  if (!drag || !owner) return null;
  const title = `Izvuci jedan nivo gore: posle #${owner.number} ${owner.title}`;
  return (
    <button
      className="icon"
      aria-label={title}
      title={title}
      onClick={(e) => {
        e.stopPropagation();
        const why = drag.move(id, { kind: "after", id: owner.id });
        if (why) window.alert(why);
      }}
    >
      ⤴
    </button>
  );
}

/** While a task is dragged in a subtask's window: places at its top that take the task out of the window, right after
 * the window's task or after one of the tasks it belongs to (deepest first), e.g. "⤴ Posle #2.1 Fiskalni računi". */
function LeaveZones({ levels }: { levels: Crumb[] }) {
  const drag = useDrag();
  if (!drag?.dragging) return null;
  const zones = [...levels].reverse().filter((c) => c.id !== drag.dragging);
  if (!zones.length) return null;
  return (
    <div className="leave-zones">
      <span className="muted small">Izvan ovog prozora:</span>
      {zones.map((c) => (
        <DropEnd key={c.id} target={{ kind: "after", id: c.id }} label={`⤴ Posle #${c.number} ${c.title}`} />
      ))}
    </div>
  );
}

/** While a task is dragged: a place at the end of a list to drop it into (also an empty branch), or (`target`) another
 * fixed place, e.g. after a task outside a subtask's window. */
export function DropEnd(props: { slot?: Slot; target?: DropTarget; label?: string; fallback?: ReactNode }) {
  const { fallback } = props;
  const drag = useDrag();
  const [over, setOver] = useState(false);
  const target: DropTarget = props.target ?? { kind: "end", slot: props.slot! };
  if (!drag?.dragging || drag.blocker(target)) return <>{fallback}</>;
  return (
    <div
      className={`drop-end ${over ? "over" : ""}`}
      onDragOver={(e) => {
        e.preventDefault();
        e.stopPropagation();
        e.dataTransfer.dropEffect = "move";
        setOver(true);
      }}
      onDragLeave={() => setOver(false)}
      onDrop={(e) => {
        e.preventDefault();
        e.stopPropagation();
        setOver(false);
        drag.drop(target);
      }}
    >
      {props.label ?? "Spustite ovde"}
    </div>
  );
}
