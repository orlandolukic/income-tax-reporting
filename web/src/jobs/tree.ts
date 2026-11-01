import { createContext, useContext } from "react";
import { children, newId, ParamValue, Task, TaskType } from "../api";

/** A list of tasks in a job: the job's own tasks (parent null), a task's subtasks, or a branch of a "Uslov"
 * ("then", "else" or the id of an INAČE AKO branch). */
export type Slot = { parent: string | null; key: string };

export const ROOT: Slot = { parent: null, key: "tasks" };

/** Where a dragged task goes: next to a task, into it (its subtasks, or a condition's AKO branch), or at
 * the end of a list. */
export type DropTarget =
  | { kind: "before" | "after" | "into"; id: string }
  | { kind: "end"; slot: Slot };

/** The deepest subtasks the page shows: top-level tasks are depth 0 (branches stay on their condition's depth). */
export const MAX_SUB_DEPTH = 6;

/** A copy of a task with everything in it (subtasks, branches), all with new ids. References inside the copy to tasks
 * that were copied too ("Iz zadatka", a Petlja's data set, a "Nastavi" jump target) point to their copies; references to
 * other tasks stay. The copy has no run result. */
export function duplicateTask(task: Task): Task {
  const ids = new Map<string, string>();
  const collect = (t: Task) => {
    ids.set(t.id, newId());
    for (const elif of t.elifs ?? []) ids.set(elif.id, newId());
    children(t).forEach(collect);
  };
  collect(task);
  const value = (v: unknown): unknown => {
    if (typeof v === "string") return ids.get(v) ?? v;
    if (Array.isArray(v)) return v.map(value);
    if (v && typeof v === "object") return Object.fromEntries(Object.entries(v).map(([k, x]) => [k, value(x)]));
    return v;
  };
  const params = (p: Record<string, ParamValue>) => value(p) as Record<string, ParamValue>;
  const copy = (t: Task): Task => ({
    ...t,
    id: ids.get(t.id)!,
    params: params(t.params),
    ...(t.subtasks ? { subtasks: t.subtasks.map(copy) } : {}),
    ...(t.then ? { then: t.then.map(copy) } : {}),
    ...(t.elifs ? { elifs: t.elifs.map((b) => ({ ...b, id: ids.get(b.id)!, params: params(b.params), then: b.then.map(copy) })) } : {}),
    ...(t.else ? { else: t.else.map(copy) } : {}),
  });
  const result = copy(task);
  return task.title ? { ...result, title: `${task.title} (kopija)` } : result;
}

function listOf(task: Task, key: string): Task[] | undefined {
  if (key === "subtasks") return task.subtasks ?? [];
  if (key === "then") return task.then;
  if (key === "else") return task.else;
  return task.elifs?.find((b) => b.id === key)?.then;
}

function withList(task: Task, key: string, list: Task[]): Task {
  if (key === "subtasks") return { ...task, subtasks: list };
  if (key === "then" || key === "else") return { ...task, [key]: list };
  return { ...task, elifs: (task.elifs ?? []).map((b) => (b.id === key ? { ...b, then: list } : b)) };
}

const KEYS = (task: Task) => ["subtasks", "then", ...(task.elifs ?? []).map((b) => b.id), "else"];

/** Apply `fn` to every list in the tree (the root list too), bottom-up; returns the new tree. */
function mapLists(tasks: Task[], slot: Slot, fn: (list: Task[], slot: Slot) => Task[]): Task[] {
  const inner = tasks.map((t) => {
    let out = t;
    for (const key of KEYS(t)) {
      const list = listOf(out, key);
      if (!list) continue;
      const next = mapLists(list, { parent: t.id, key }, fn);
      // A task without subtasks keeps no "subtasks" key unless one is moved into it.
      if (key !== "subtasks" || t.subtasks || next.length) out = withList(out, key, next);
    }
    return out;
  });
  return fn(inner, slot);
}

export function findTask(tasks: Task[], id: string): Task | undefined {
  for (const t of tasks) {
    if (t.id === id) return t;
    const found = findTask(children(t), id);
    if (found) return found;
  }
  return undefined;
}

/** Subtask depth of the task with this id (0 = top level), or -1. */
function depthOf(tasks: Task[], id: string, depth = 0): number {
  for (const t of tasks) {
    if (t.id === id) return depth;
    for (const key of KEYS(t)) {
      const d = depthOf(listOf(t, key) ?? [], id, key === "subtasks" ? depth + 1 : depth);
      if (d >= 0) return d;
    }
  }
  return -1;
}

/** How many subtask levels a task has below it. */
function height(task: Task): number {
  let h = 0;
  for (const key of KEYS(task)) {
    for (const c of listOf(task, key) ?? []) h = Math.max(h, height(c) + (key === "subtasks" ? 1 : 0));
  }
  return h;
}

/** Whether a task can hold other tasks dropped onto it: a condition (its AKO branch) or a type with subtasks. */
export function canHold(task: Task, type: TaskType | undefined): boolean {
  return task.type === "condition" || !!(type?.returnsRows || type?.subtasksOnce || type?.subtasksWhen);
}

/** Depth the dropped task would get, or -1 if the target isn't in the tree. */
function targetDepth(tasks: Task[], target: DropTarget): number {
  if (target.kind === "end") {
    if (target.slot.parent === null) return 0;
    const d = depthOf(tasks, target.slot.parent);
    return d < 0 ? -1 : d + (target.slot.key === "subtasks" ? 1 : 0);
  }
  const d = depthOf(tasks, target.id);
  if (d < 0) return -1;
  if (target.kind !== "into") return d;
  return findTask(tasks, target.id)?.type === "condition" ? d : d + 1;
}

/** Why the task can't be dropped there ("" if it can). */
export function dropBlocker(tasks: Task[], id: string, target: DropTarget, types: Record<string, TaskType>): string {
  const task = findTask(tasks, id);
  if (!task) return "Zadatak ne postoji.";
  const targetId = target.kind === "end" ? target.slot.parent : target.id;
  const nextToItself = targetId === id && (target.kind === "before" || target.kind === "after");
  if (targetId && !nextToItself && (targetId === id || findTask(children(task), targetId))) {
    return "Zadatak ne može u sam sebe.";
  }
  if (target.kind === "into") {
    const holder = findTask(tasks, target.id);
    if (!holder || !canHold(holder, types[holder.type])) return "Ovaj zadatak ne može imati podzadatke.";
  }
  const depth = targetDepth(tasks, target);
  if (depth < 0) return "Mesto ne postoji.";
  if (depth + height(task) > MAX_SUB_DEPTH) return `Najviše ${MAX_SUB_DEPTH} nivoa podzadataka.`;
  return "";
}

/** The tree with task `id` moved to `target` (unchanged if it can't go there). */
export function moveTask(tasks: Task[], id: string, target: DropTarget, types: Record<string, TaskType>): Task[] {
  if (dropBlocker(tasks, id, target, types)) return tasks;
  if (target.kind !== "end" && target.id === id) return tasks; // dropped next to itself
  const moved = findTask(tasks, id)!;
  const without = mapLists(tasks, ROOT, (list) => list.filter((t) => t.id !== id));
  if (target.kind === "into") {
    const holder = findTask(without, target.id)!;
    const key = holder.type === "condition" ? "then" : "subtasks";
    return mapLists(without, ROOT, (list) =>
      list.map((t) => (t.id === target.id ? withList(t, key, [...(listOf(t, key) ?? []), moved]) : t)),
    );
  }
  return mapLists(without, ROOT, (list, slot) => {
    if (target.kind === "end") {
      return slot.parent === target.slot.parent && slot.key === target.slot.key ? [...list, moved] : list;
    }
    const i = list.findIndex((t) => t.id === target.id);
    if (i < 0) return list;
    const at = target.kind === "before" ? i : i + 1;
    return [...list.slice(0, at), moved, ...list.slice(at)];
  });
}

/** Drag state shared by every task row and list of the job page. */
export type DragApi = {
  dragging: string | null;
  start: (id: string) => void;
  end: () => void;
  blocker: (target: DropTarget) => string; // "" if the dragged task can go there
  drop: (target: DropTarget) => void;
  // Move a task without dragging (e.g. "⤴" out of the list it is in): "" if done, else why it can't go there.
  move: (id: string, target: DropTarget) => string;
};

export const DragContext = createContext<DragApi | null>(null);

export const useDrag = () => useContext(DragContext);
