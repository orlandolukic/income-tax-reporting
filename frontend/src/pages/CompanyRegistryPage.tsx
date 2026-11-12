import { GfiTableView } from "@/components/GfiTableView";
import { Main } from "@/components/layout/Main";

/** All companies with their complete GFI data; company details are editable here. */
export default function CompanyRegistryPage() {
  return (
    <Main>
      <GfiTableView
        title="Company Registry"
        description="All GFI columns. Company name, PIB and referent can be edited here; changes save automatically and also show on Home."
        variant="registry"
      />
    </Main>
  );
}
