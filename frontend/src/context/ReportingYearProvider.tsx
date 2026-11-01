import { createContext, useContext, useEffect, useState, type ReactNode } from "react";
import { getLogger } from "@/logger";

const logger = getLogger("reportingYear");

// Selected year is kept for the browser session and cleared on logout.
const STORAGE_KEY = "reporting-year";

type ReportingYearState = {
  years: number[];
  selectedYear: number | null;
  setSelectedYear: (year: number) => void;
  loading: boolean;
  error: string | null;
};

const ReportingYearContext = createContext<ReportingYearState | null>(null);

function readStoredYear(): number | null {
  try {
    const value = Number(sessionStorage.getItem(STORAGE_KEY));
    return Number.isInteger(value) && value > 0 ? value : null;
  } catch {
    return null;
  }
}

export function clearStoredReportingYear() {
  try {
    sessionStorage.removeItem(STORAGE_KEY);
  } catch {
    // Storage unavailable: nothing to clear.
  }
}

export function ReportingYearProvider({ children }: { children: ReactNode }) {
  const [years, setYears] = useState<number[]>([]);
  const [selectedYear, setSelectedYearState] = useState<number | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetch("/api/reporting-years")
      .then((res) => {
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        return res.json();
      })
      .then((data: { years: number[] }) => {
        setYears(data.years);
        // Keep the stored year if it is still available, otherwise default to the newest.
        const stored = readStoredYear();
        setSelectedYearState(stored !== null && data.years.includes(stored) ? stored : (data.years[0] ?? null));
        logger.debug("Reporting years loaded", data.years);
      })
      .catch((err) => {
        logger.error("Failed to load reporting years", err);
        setError("Unable to load reporting years.");
      })
      .finally(() => setLoading(false));
  }, []);

  function setSelectedYear(year: number) {
    try {
      sessionStorage.setItem(STORAGE_KEY, String(year));
    } catch {
      // Ignore: the selection still applies until reload.
    }
    setSelectedYearState(year);
    logger.info(`Reporting year selected: ${year}`);
  }

  return (
    <ReportingYearContext.Provider value={{ years, selectedYear, setSelectedYear, loading, error }}>
      {children}
    </ReportingYearContext.Provider>
  );
}

export function useReportingYear(): ReportingYearState {
  const ctx = useContext(ReportingYearContext);
  if (!ctx) throw new Error("useReportingYear must be used inside ReportingYearProvider");
  return ctx;
}
