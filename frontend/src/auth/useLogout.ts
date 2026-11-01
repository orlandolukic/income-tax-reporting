import { useNavigate } from "react-router";
import { clearStoredReportingYear } from "@/context/ReportingYearProvider";
import { useAuth } from "./AuthContext";

/** Logs out, clears session-scoped selections and returns to the Login page. */
export function useLogout() {
  const { logout } = useAuth();
  const navigate = useNavigate();

  return async () => {
    await logout();
    clearStoredReportingYear();
    navigate("/login", { replace: true });
  };
}
