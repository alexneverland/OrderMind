import { useEffect, useRef, useState } from "react";
import { analyzeRules, type RulesProposal } from "../api/rules";
import type { PalletConfig, Product } from "../types";
import { Alert, Spinner } from "./ui";

type PalletProposal = NonNullable<NonNullable<RulesProposal["export_patch"]>["palletization"]>;

export function PalletRulesAssistant({ companyId, products, disabled, onBusyChange, onUse }: {
  companyId: number;
  products: Product[];
  disabled: boolean;
  onBusyChange: (busy: boolean) => void;
  onUse: (config: PalletConfig) => void;
}) {
  const [description, setDescription] = useState("");
  const [proposal, setProposal] = useState<RulesProposal | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const active = useRef(true);
  useEffect(() => {
    active.current = true;
    return () => { active.current = false; };
  }, []);

  const analyze = async () => {
    if (busy || disabled) return;
    setBusy(true); onBusyChange(true); setError(""); setMessage(""); setProposal(null);
    try {
      const result = await analyzeRules(companyId, description.trim());
      if (active.current) setProposal(result);
    } catch (cause) {
      if (active.current) setError((cause as Error).message);
    } finally {
      if (active.current) { setBusy(false); onBusyChange(false); }
    }
  };
  const pallet = proposal?.export_patch?.palletization;
  const selectedIds = pallet?.dedicated_groups.flatMap((group) => group.products.map((product) => product.product_id)) ?? [];
  const unresolved = selectedIds.some((id) => !products.some((product) => product.id === id));
  const duplicate = new Set(selectedIds.filter((id) => id !== null)).size !== selectedIds.filter((id) => id !== null).length;
  const chooseProduct = (groupIndex: number, productIndex: number, id: number | null) => {
    if (!proposal || !pallet) return;
    setProposal({ ...proposal, export_patch: { ...proposal.export_patch!, palletization: {
      ...pallet, dedicated_groups: pallet.dedicated_groups.map((group, gi) => gi !== groupIndex ? group : {
        ...group, products: group.products.map((product, pi) => pi !== productIndex ? product : { ...product, product_id: id }),
      }),
    } } });
  };
  const useProposal = (value: PalletProposal) => {
    if (unresolved || duplicate || busy || disabled) return;
    onUse({
      enabled: value.enabled,
      dedicated_groups: value.dedicated_groups.map((group) => ({ name: group.name, product_ids: group.products.map((product) => product.product_id!) })),
      automatic_pallets: { ...value.automatic_pallets },
      output: { ...value.output },
    });
    setProposal(null);
    setMessage("Pallet settings copied to this profile's draft. Review them below, then select Save profile.");
  };
  const otherChanges = proposal && (Object.values(proposal.settings_patch).some((value) => value !== null) ||
    proposal.quantity_rules.length > 0 || Object.entries(proposal.export_patch ?? {}).some(([key, value]) =>
      key !== "palletization" && key !== "profile_id" && value != null));

  return <section className="stack-form" aria-label="Pallet rules assistant">
    <h3>Describe pallet planning to AI</h3>
    <p>Write in Greek or English. The selected AI provider proposes settings for this profile; nothing is saved automatically.</p>
    <label>Describe the full pallet setup
      <textarea rows={5} maxLength={6000} value={description} disabled={busy || disabled}
        placeholder={"Κάθε παλέτα έως 500 κιλά και έως 20 γραμμές εξαγωγής, μαζί με τα δώρα. Κάθε παλέτα σε ξεχωριστό φύλλο Excel. Οι κωδικοί ABC και DEF μαζί σε δική τους παλέτα."}
        onChange={(event) => { setDescription(event.target.value); setProposal(null); setMessage(""); }} />
    </label>
    <small>Describe capacities, dedicated product groups, how gift rows count, and the Excel layout. A proposal replaces the complete pallet configuration of this draft.</small>
    <button type="button" className="button primary" disabled={busy || disabled || description.trim().length < 3} onClick={() => void analyze()}>
      {busy ? <Spinner /> : "Analyze pallet rules"}
    </button>
    <Alert message={error} />
    {message && <p role="status">{message}</p>}
    {proposal && <section className="panel padded stack-form" aria-label="Pallet proposal">
      <h4>Review the proposed pallet setup</h4>
      {pallet ? <>
        <p>Palletization: {pallet.enabled ? "Enabled" : "Disabled"}</p>
        <p>Maximum weight: {pallet.automatic_pallets.max_weight_kg ?? "No weight limit"}{pallet.automatic_pallets.max_weight_kg != null ? " kg" : ""}</p>
        <p>Maximum rows: {pallet.automatic_pallets.max_rows ?? "No row limit"}. Counting: {pallet.automatic_pallets.row_count_mode === "output_rows" ? "actual exported rows (including separate gift rows)" : "logical product lines"}.</p>
        <p>Layout: {{ single_sheet_sections: "One worksheet, pallets one below another", multi_sheet_workbook: "One worksheet per pallet", separate_workbook_per_pallet: "Separate workbooks in one ZIP" }[pallet.output.layout]}.</p>
        <p>Pallet titles: {pallet.output.show_pallet_title ? "Yes" : "No"} · Repeat headers: {pallet.output.repeat_headers ? "Yes" : "No"} · Blank rows: {pallet.output.blank_rows_between_pallets}</p>
        <p>Packing follows approved order-line order.</p>
        {!pallet.dedicated_groups.length && <p>No dedicated product groups.</p>}
        {pallet.dedicated_groups.map((group, gi) => <div className="candidate" key={gi}>
          <strong>{group.name}</strong>
          {group.products.map((reference, pi) => <label key={pi}>Product {reference.reference}
            <select value={products.some((product) => product.id === reference.product_id) ? reference.product_id! : ""}
              onChange={(event) => chooseProduct(gi, pi, Number(event.target.value) || null)}>
              <option value="">Select matching catalog product</option>
              {products.map((product) => <option key={product.id} value={product.id}>{product.sku} · {product.description}</option>)}
            </select>
          </label>)}
        </div>)}
        {unresolved && <p role="note">Select a company catalog product for every unresolved reference.</p>}
        {duplicate && <p role="note">Each product may belong to only one dedicated group and cannot be repeated.</p>}
      </> : <p>No supported pallet configuration was proposed. Specify at least a weight or row capacity, or check the selected AI provider in Settings.</p>}
      {proposal.unsupported_rules.map((item, index) => <p role="note" key={index}>Unsupported: {item.text} — {item.reason}</p>)}
      {otherChanges && <p role="note">This assistant uses only pallet settings. Company rules, promotions, and other export conventions can be configured separately in Settings.</p>}
      <div className="line-actions">
        <button type="button" className="button primary" disabled={!pallet || unresolved || duplicate || busy || disabled}
          onClick={() => { if (pallet) useProposal(pallet); }}>Use pallet proposal</button>
        <button type="button" className="button" onClick={() => setProposal(null)}>Discard proposal</button>
      </div>
    </section>}
  </section>;
}
