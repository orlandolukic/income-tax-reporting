import { answer, Prompt } from "./api";

export default function Done({ prompt }: { prompt: Extract<Prompt, { kind: "done" }> }) {
  const { error } = prompt.data;
  return (
    <div className="card narrow">
      <h2>{error ? "Greška" : "Gotovo"}</h2>
      {error && <p className="error">{error}</p>}
      <div className="buttons">
        <button className="primary" onClick={() => answer(prompt.id, true)}>
          Završi
        </button>
      </div>
    </div>
  );
}
