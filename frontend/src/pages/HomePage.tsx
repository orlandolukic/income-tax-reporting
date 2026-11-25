import { GfiTableView } from "@/components/GfiTableView";
import { Main } from "@/components/layout/Main";

export default function HomePage() {
  return (
    <Main>
      {/* View only (user, 2026-11-17): the statuses follow the PB-1 report steps, the company
          details are edited on Edit Company Data. */}
      <GfiTableView
        title="Početna"
        variant="home"
        description="Pregled svih firmi, samo za gledanje. Statusi se postavljaju koracima u PB-1 (preliminarni gotov, GFI gotov, konačni gotov, predat), a podaci firme se menjaju na stranici Izmena podataka firmi."
      />
    </Main>
  );
}
