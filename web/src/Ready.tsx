import { answer, Prompt } from "./api";

/** Logged in and a company is open: jobs can run until the user finishes. */
export default function Ready({ prompt }: { prompt: Extract<Prompt, { kind: "ready" }> }) {
  return (
    <div className="card narrow">
      <h2>Spremno</h2>
      <p>
        {prompt.data.company ? (
          <>
            Otvorena firma: <strong>{prompt.data.company}</strong>.
          </>
        ) : (
          "Firma je otvorena u pretraživaču."
        )}{" "}
        Poslove pokrećete na stranici „Poslovi“, a izveštaje na stranici „Izveštaji“.
      </p>
      <div className="buttons">
        <a className="button primary" href="#/poslovi">
          Otvori poslove
        </a>
        <a className="button" href="#/izvestaji">
          Izveštaji
        </a>
        <button onClick={() => answer(prompt.id, true)}>Zatvori pretraživač i završi</button>
      </div>
    </div>
  );
}
