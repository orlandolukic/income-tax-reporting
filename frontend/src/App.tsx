import { BrowserRouter, Navigate, Route, Routes } from "react-router";
import { AuthProvider } from "./auth/AuthContext";
import ProtectedRoute from "./auth/ProtectedRoute";
import { AuthenticatedLayout } from "./components/layout/AuthenticatedLayout";
import { TooltipProvider } from "./components/ui/tooltip";
import { ThemeProvider } from "./context/ThemeProvider";
import CompanyRegistryPage from "./pages/CompanyRegistryPage";
import HomePage from "./pages/HomePage";
import LoginPage from "./pages/LoginPage";
import MigrationPage from "./pages/MigrationPage";
import Pb1Page from "./pages/Pb1Page";

export default function App() {
  return (
    <ThemeProvider>
      <TooltipProvider delayDuration={0}>
        <AuthProvider>
          <BrowserRouter>
            <Routes>
              <Route path="/login" element={<LoginPage />} />
              <Route
                element={
                  <ProtectedRoute>
                    <AuthenticatedLayout />
                  </ProtectedRoute>
                }
              >
                <Route path="/" element={<HomePage />} />
                <Route path="/company-registry" element={<CompanyRegistryPage />} />
                <Route path="/migration" element={<MigrationPage />} />
                <Route path="/companies/:year/:row/pb1" element={<Pb1Page />} />
                <Route path="/companies/:year/:row/pb1/:tab" element={<Pb1Page />} />
              </Route>
              <Route path="*" element={<Navigate to="/" replace />} />
            </Routes>
          </BrowserRouter>
        </AuthProvider>
      </TooltipProvider>
    </ThemeProvider>
  );
}
