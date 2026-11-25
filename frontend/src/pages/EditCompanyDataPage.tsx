import { GfiTableView } from "@/components/GfiTableView";
import { Main } from "@/components/layout/Main";

/**
 * Edit Company Data (formerly "Company Registry"): the only page where the company details
 * (NAZIV, PIB, REFERENT, office) are edited. The status columns are shown read-only and shaded:
 * they are set only by the PB-1 report steps (user, 2026-11-17). The formula columns are not
 * shown (nothing is entered in them).
 */
export default function EditCompanyDataPage() {
  return (
    <Main>
      <GfiTableView
        title="Izmena podataka firmi"
        description="Ovde se menjaju naziv firme, PIB, referent i kancelarija (samo na ovoj stranici). Statusne kolone se ne menjaju ručno: postavljaju ih koraci u PB-1 (preliminarni gotov, GFI gotov, konačni gotov, predat). Izmene se čuvaju automatski i vide se i na Početnoj."
        variant="registry"
      />
    </Main>
  );
}
