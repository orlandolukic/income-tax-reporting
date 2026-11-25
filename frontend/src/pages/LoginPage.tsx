import { useState, type FormEvent } from "react";
import { Loader2 } from "lucide-react";
import { AppLogo } from "@/components/AppLogo";
import { Navigate, useNavigate } from "react-router";
import { useAuth } from "@/auth/AuthContext";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { getLogger } from "@/logger";

const logger = getLogger("LoginPage");

export default function LoginPage() {
  const { username: currentUser, loading, login, sessionExpired } = useAuth();
  const navigate = useNavigate();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  if (loading) return null;
  if (currentUser) return <Navigate to="/" replace />;

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setSubmitting(true);
    try {
      if (await login(username, password)) {
        navigate("/", { replace: true });
      } else {
        setError("Pogrešno korisničko ime ili lozinka.");
        setPassword("");
      }
    } catch (err) {
      logger.error("Login request failed", err);
      setError("Server nije dostupan. Pokušajte ponovo.");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="bg-muted/40 flex min-h-svh items-center justify-center p-4">
      <div className="flex w-full max-w-sm flex-col gap-6">
        <div className="flex items-center justify-center gap-2">
          <AppLogo />
          <span className="text-xl font-semibold">Izveštavanje o porezu na dobit</span>
        </div>
        <Card className="gap-4">
          <CardHeader>
            <CardTitle className="text-lg tracking-tight">Prijava</CardTitle>
            <CardDescription>Unesite korisničko ime i lozinku za prijavu.</CardDescription>
          </CardHeader>
          <CardContent>
            <form onSubmit={handleSubmit} className="grid gap-4">
              {sessionExpired && (
                <Alert>
                  <AlertDescription>
                    Sesija je istekla. Prijavite se ponovo; nesačuvane izmene u tabelama su zadržane i biće sačuvane.
                  </AlertDescription>
                </Alert>
              )}
              <div className="grid gap-2">
                <Label htmlFor="username">Korisničko ime</Label>
                <Input
                  id="username"
                  value={username}
                  onChange={(e) => setUsername(e.target.value)}
                  autoComplete="username"
                  required
                />
              </div>
              <div className="grid gap-2">
                <Label htmlFor="password">Lozinka</Label>
                <Input
                  id="password"
                  type="password"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  autoComplete="current-password"
                  aria-invalid={error ? true : undefined}
                  required
                />
              </div>
              {error && (
                <Alert variant="destructive">
                  <AlertDescription>{error}</AlertDescription>
                </Alert>
              )}
              <Button type="submit" className="mt-2" disabled={submitting}>
                {submitting && <Loader2 className="animate-spin" />}
                Prijavi se
              </Button>
            </form>
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
