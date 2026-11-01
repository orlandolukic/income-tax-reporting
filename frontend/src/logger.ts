// Client-side logger supporting DEBUG, INFO, WARNING, ERROR and CRITICAL.
// The minimum level comes from VITE_LOG_LEVEL (default: INFO).

const LEVELS = { DEBUG: 10, INFO: 20, WARNING: 30, ERROR: 40, CRITICAL: 50 } as const;
type Level = keyof typeof LEVELS;

const configured = (import.meta.env.VITE_LOG_LEVEL ?? "INFO").toUpperCase();
const minLevel = configured in LEVELS ? LEVELS[configured as Level] : LEVELS.INFO;

function log(level: Level, name: string, message: string, ...args: unknown[]) {
  if (LEVELS[level] < minLevel) return;
  const line = `${new Date().toISOString()} | ${level.padEnd(8)} | ${name} | ${message}`;
  const sink =
    level === "DEBUG" ? console.debug
    : level === "INFO" ? console.info
    : level === "WARNING" ? console.warn
    : console.error;
  sink(line, ...args);
}

export function getLogger(name: string) {
  return {
    debug: (msg: string, ...args: unknown[]) => log("DEBUG", name, msg, ...args),
    info: (msg: string, ...args: unknown[]) => log("INFO", name, msg, ...args),
    warning: (msg: string, ...args: unknown[]) => log("WARNING", name, msg, ...args),
    error: (msg: string, ...args: unknown[]) => log("ERROR", name, msg, ...args),
    critical: (msg: string, ...args: unknown[]) => log("CRITICAL", name, msg, ...args),
  };
}
