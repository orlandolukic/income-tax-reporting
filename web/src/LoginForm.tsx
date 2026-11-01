import { FormEvent, useState } from "react";
import { answer, Prompt } from "./api";

export default function LoginForm({ prompt }: { prompt: Extract<Prompt, { kind: "login" }> }) {
  const [username, setUsername] = useState(prompt.data.username);
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");

  function submit(e: FormEvent) {
    e.preventDefault();
    if (!username.trim() || !password) {
      setError("Unesite korisničko ime i lozinku.");
      return;
    }
    answer(prompt.id, { username, password });
  }

  return (
    <form className="card narrow" onSubmit={submit} onKeyDown={(e) => e.key === "Escape" && answer(prompt.id, null)}>
      <h2>Prijava</h2>
      {prompt.data.message && <p className="warning">{prompt.data.message}</p>}
      <label>
        Korisničko ime
        <input
          value={username}
          onChange={(e) => setUsername(e.target.value)}
          autoFocus={!prompt.data.username}
          autoComplete="username"
        />
      </label>
      <label>
        Lozinka
        <input
          type="password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          autoFocus={!!prompt.data.username}
          autoComplete="current-password"
        />
      </label>
      {error && <p className="error">{error}</p>}
      <div className="buttons">
        <button type="submit" className="primary">Prijava</button>
        <button type="button" onClick={() => answer(prompt.id, null)}>Otkaži</button>
      </div>
    </form>
  );
}
