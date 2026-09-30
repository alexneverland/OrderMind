import type { PalletConfig, Product } from "../types";

export const emptyPalletConfig = (): PalletConfig => ({
  enabled: false, dedicated_groups: [],
  automatic_pallets: { max_weight_kg: null, max_rows: null, row_count_mode: "output_rows", packing_strategy: "sequential" },
  output: { layout: "single_sheet_sections", show_pallet_title: true, repeat_headers: false, blank_rows_between_pallets: 1 },
});

export function PalletEditor({ value, products, onChange }: {
  value: PalletConfig;
  products: Product[];
  onChange: (value: PalletConfig) => void;
}) {
  const changeAutomatic = (patch: Partial<PalletConfig["automatic_pallets"]>) =>
    onChange({ ...value, automatic_pallets: { ...value.automatic_pallets, ...patch } });
  const changeOutput = (patch: Partial<PalletConfig["output"]>) =>
    onChange({ ...value, output: { ...value.output, ...patch } });
  const changeGroup = (index: number, patch: Partial<PalletConfig["dedicated_groups"][number]>) =>
    onChange({ ...value, dedicated_groups: value.dedicated_groups.map((group, i) => i === index ? { ...group, ...patch } : group) });
  return <fieldset className="stack-form">
    <legend>Pallet planning</legend>
    <label className="check-row"><input type="checkbox" checked={value.enabled}
      onChange={(event) => onChange({ ...value, enabled: event.target.checked })} /> Enable palletization</label>
    {value.enabled && <>
      <h4>Dedicated pallet groups</h4>
      {value.dedicated_groups.map((group, index) => <div className="candidate" key={index}>
        <label>Group name<input value={group.name} required maxLength={100}
          onChange={(event) => changeGroup(index, { name: event.target.value })} /></label>
        <details><summary>Products ({group.product_ids.length})</summary>
          <div className="stack-form">{products.map((product) => <label className="check-row" key={product.id}>
            <input type="checkbox" checked={group.product_ids.includes(product.id)}
              disabled={!group.product_ids.includes(product.id) && value.dedicated_groups.some((other, i) => i !== index && other.product_ids.includes(product.id))}
              onChange={(event) => changeGroup(index, { product_ids: event.target.checked ? [...group.product_ids, product.id] : group.product_ids.filter((id) => id !== product.id) })} />
            {product.sku} · {product.description}
          </label>)}</div>
        </details>
        <button type="button" className="button subtle" onClick={() => onChange({ ...value, dedicated_groups: value.dedicated_groups.filter((_, i) => i !== index) })}>Remove group</button>
      </div>)}
      <button type="button" className="button" onClick={() => onChange({ ...value, dedicated_groups: [...value.dedicated_groups, { name: `Group ${value.dedicated_groups.length + 1}`, product_ids: [] }] })}>+ Add group</button>
      <h4>Automatic pallets</h4>
      <p>Set at least one limit. Gift rows count separately in actual exported rows mode.</p>
      <label>Maximum weight (kg)<input type="number" min="0.000001" step="any" value={value.automatic_pallets.max_weight_kg ?? ""}
        onChange={(event) => changeAutomatic({ max_weight_kg: event.target.value ? Number(event.target.value) : null })} /></label>
      <label>Maximum rows<input type="number" min="1" max="10000" step="1" value={value.automatic_pallets.max_rows ?? ""}
        onChange={(event) => changeAutomatic({ max_rows: event.target.value ? Number(event.target.value) : null })} /></label>
      <label>Count rows as<select value={value.automatic_pallets.row_count_mode}
        onChange={(event) => changeAutomatic({ row_count_mode: event.target.value as PalletConfig["automatic_pallets"]["row_count_mode"] })}>
        <option value="output_rows">Actual exported product rows</option><option value="logical_product_lines">Logical product lines</option>
      </select></label>
      <p>Packing strategy: sequential in approved order-line order.</p>
      <h4>Output</h4>
      <label>Layout<select value={value.output.layout}
        onChange={(event) => changeOutput({ layout: event.target.value as PalletConfig["output"]["layout"] })}>
        <option value="single_sheet_sections">One worksheet, pallets one below another</option>
        <option value="multi_sheet_workbook">One worksheet per pallet</option>
        <option value="separate_workbook_per_pallet">Separate workbooks in one ZIP</option>
      </select></label>
      <label className="check-row"><input type="checkbox" checked={value.output.show_pallet_title}
        onChange={(event) => changeOutput({ show_pallet_title: event.target.checked })} /> Show pallet title</label>
      {value.output.layout === "single_sheet_sections" && <>
        <label className="check-row"><input type="checkbox" checked={value.output.repeat_headers}
          onChange={(event) => changeOutput({ repeat_headers: event.target.checked })} /> Repeat column headers</label>
        <label>Blank rows between pallets<input type="number" min="0" max="20" step="1" value={value.output.blank_rows_between_pallets}
          onChange={(event) => changeOutput({ blank_rows_between_pallets: Number(event.target.value) })} /></label>
      </>}
    </>}
  </fieldset>;
}
