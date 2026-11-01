import { createContext, useContext, useEffect, useState, type ReactNode } from "react";
import { getLogger } from "../logger";

const logger = getLogger("auth");

type AuthState = {
  username: string | null;
  loading: boolean;
  login: (username: string, password: string) => Promise<boolean>;
  logout: () => Promise<void>;
  /** True after an API call was rejected because the session is no longer valid. */
  sessionExpired: boolean;
  /** Call when the backend answers 401 for a logged-in user; returns to the Login page. */
  markSessionExpired: () => void;
};

const AuthContext = createContext<AuthState | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [username, setUsername] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [sessionExpired, setSessionExpired] = useState(false);

  // Restore an existing session (cookie) on page load.
  useEffect(() => {
    fetch("/api/auth/me")
      .then((res) => (res.ok ? res.json() : null))
      .then((data: { username: string } | null) => setUsername(data?.username ?? null))
      .catch((err) => logger.error("Session check failed", err))
      .finally(() => setLoading(false));
  }, []);

  async function login(user: string, password: string): Promise<boolean> {
    const res = await fetch("/api/auth/login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ username: user, password }),
    });
    if (res.status === 401) {
      logger.warning("Login rejected");
      return false;
    }
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data: { username: string } = await res.json();
    setUsername(data.username);
    setSessionExpired(false);
    logger.info("Logged in");
    return true;
  }

  async function logout(): Promise<void> {
    try {
      await fetch("/api/auth/logout", { method: "POST" });
    } catch (err) {
      logger.error("Logout request failed", err);
    }
    setUsername(null);
    setSessionExpired(false);
    logger.info("Logged out");
  }

  function markSessionExpired() {
    if (username === null) return;
    logger.warning("Session expired");
    setUsername(null);
    setSessionExpired(true);
  }

  return (
    <AuthContext.Provider value={{ username, loading, login, logout, sessionExpired, markSessionExpired }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth(): AuthState {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used inside AuthProvider");
  return ctx;
}
