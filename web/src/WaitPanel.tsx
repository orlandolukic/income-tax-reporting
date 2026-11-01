import { answer, Prompt } from "./api";

export default function WaitPanel({ prompt }: { prompt: Extract<Prompt, { kind: "wait" }> }) {
  return (
    <div className="card narrow">
      <p className="pre-line">{prompt.data.message}</p>
      <div className="buttons">
        <button className="primary" onClick={() => answer(prompt.id, true)}>Nastavi</button>
        <button onClick={() => answer(prompt.id, false)}>Otkaži</button>
      </div>
    </div>
  );
}
