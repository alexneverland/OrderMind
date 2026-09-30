import { useEffect, useState } from "react";
import {
  createProfile,
  deleteProfile,
  getProfiles,
  getSourceFields,
  updateProfile,
  type ProfileInput,
} from "../api/exportProfiles";
import { useCompany } from "../components/AppShell";
import { PalletEditor, emptyPalletConfig } from "../components/PalletEditor";
import { getProducts } from "../api/masterData";
import { Alert, Empty, Spinner } from "../components/ui";
import { useAsync } from "../hooks/useAsync";
import type { ExportProfile, Mapping, PalletConfig, Product } from "../types";

const blankMapping = (): Mapping => ({
  column_order: 1,
  output_column_name: "",
  mapping_type: "source_field",
  source_field: "",
  constant_value: null,
});
function ProfileEditor({
  companyId,
  profile,
  fields,
  onClose,
  onSave,
}: {
  companyId: number;
  profile: ExportProfile | null;
  fields: Record<string, string>;
  onClose: () => void;
  onSave: () => Promise<void>;
}) {
  const [name, setName] = useState(profile?.name || "");
  const [format, setFormat] = useState(profile?.format || "xlsx");
  const [delimiter, setDelimiter] = useState(profile?.delimiter || ",");
  const [encoding, setEncoding] = useState(profile?.encoding || "utf-8-sig");
  const [header, setHeader] = useState(profile?.include_header ?? true);
  const [bonusSeparateRow, setBonusSeparateRow] = useState(profile?.bonus_separate_row ?? false);
  const [bonusMarker, setBonusMarker] = useState(profile?.bonus_marker ?? "");
  const [quantityOutputUnit, setQuantityOutputUnit] = useState<"source" | "piece">(profile?.quantity_output_unit ?? "source");
  const [palletization, setPalletization] = useState<PalletConfig>(profile?.palletization ?? emptyPalletConfig());
  const [products, setProducts] = useState<Product[]>([]);
  useEffect(() => { void getProducts(companyId).then(setProducts).catch(() => setProducts([])); }, [companyId]);
  const [mappings, setMappings] = useState<Mapping[]>(
    profile?.field_mappings.map(
      ({
        column_order,
        output_column_name,
        mapping_type,
        source_field,
        constant_value,
      }) => ({
        column_order,
        output_column_name,
        mapping_type,
        source_field,
        constant_value,
      }),
    ) || [blankMapping()],
  );
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const update = (i: number, patch: Partial<Mapping>) =>
    setMappings((items) =>
      items.map((m, j) => (i === j ? { ...m, ...patch } : m)),
    );
  const move = (i: number, delta: number) =>
    setMappings((items) => {
      const next = [...items];
      const other = i + delta;
      if (other < 0 || other >= next.length) return items;
      [next[i], next[other]] = [next[other], next[i]];
      return next;
    });
  const save = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError("");
    const input: ProfileInput = {
      company_id: companyId,
      name,
      format,
      delimiter,
      encoding,
      include_header: header,
      bonus_separate_row: format === "order_sheet" && bonusSeparateRow,
      bonus_marker: format === "order_sheet" && bonusSeparateRow ? bonusMarker : null,
      quantity_output_unit: format === "order_sheet" ? quantityOutputUnit : "source",
      convert_case_using_pieces_per_case: format === "order_sheet" && quantityOutputUnit === "piece",
      palletization: format === "order_sheet" ? palletization : emptyPalletConfig(),
      mappings: format === "order_sheet" ? [] : mappings.map((m, i) => ({
        ...m,
        column_order: i + 1,
        source_field: m.mapping_type === "source_field" ? m.source_field : null,
        constant_value: m.mapping_type === "constant" ? m.constant_value : null,
      })),
    };
    try {
      if (profile) await updateProfile(profile.id, input);
      else await createProfile(input);
      await onSave();
      onClose();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };
  return (
    <div
      className="modal-backdrop"
      onMouseDown={() => {
        if (!busy) onClose();
      }}
    >
      <section
        className="modal wide"
        role="dialog"
        aria-modal="true"
        aria-label={profile ? "Edit export profile" : "Create export profile"}
        onMouseDown={(e) => e.stopPropagation()}
      >
        <div className="modal-head">
          <div>
            <div className="eyebrow">EXPORT CONFIGURATION</div>
            <h2>{profile ? "Edit profile" : "Create profile"}</h2>
          </div>
          <button
            className="icon-button"
            onClick={onClose}
            aria-label="Close"
            disabled={busy}
          >
            ×
          </button>
        </div>
        <Alert message={error} />
        <form onSubmit={(e) => void save(e)} className="stack-form">
          <div className="form-grid">
            <label>
              Name
              <input
                value={name}
                onChange={(e) => setName(e.target.value)}
                required
                maxLength={100}
              />
            </label>
            <label>
              Format
              <select
                value={format}
                onChange={(e) => setFormat(e.target.value)}
                disabled={!!profile && profile.format === "order_sheet"}
              >
                <option value="xlsx">XLSX</option>
                <option value="csv">CSV</option>
                <option value="json">JSON</option>
                <option value="order_sheet" disabled={!!profile && profile.format !== "order_sheet"}>4-column order sheet</option>
              </select>
            </label>
            <label>
              Delimiter
              <select
                value={delimiter}
                onChange={(e) => setDelimiter(e.target.value)}
                disabled={format !== "csv"}
              >
                <option value=",">Comma (,)</option>
                <option value=";">Semicolon (;)</option>
                <option value="\t">Tab</option>
                <option value="|">Pipe (|)</option>
              </select>
            </label>
            <label>
              Encoding
              <select
                value={encoding}
                onChange={(e) => setEncoding(e.target.value)}
                disabled={format !== "csv"}
              >
                <option value="utf-8-sig">UTF-8 BOM</option>
                <option value="utf-8">UTF-8</option>
              </select>
            </label>
          </div>
          <label className="check-row">
            <input
              type="checkbox"
              checked={header}
              onChange={(e) => setHeader(e.target.checked)}
            />{" "}
            Include header row
          </label>
          {format === "order_sheet" && (
            <div className="stack-form">
              <p>Fixed columns: SKU, description, bonus marker, quantity. Choose the business rules for this profile.</p>
              <label className="check-row"><input type="checkbox" checked={bonusSeparateRow}
                onChange={(e) => setBonusSeparateRow(e.target.checked)} /> Separate bonus row</label>
              {bonusSeparateRow && <label>Bonus marker
                <input value={bonusMarker} maxLength={20} required
                  onChange={(e) => setBonusMarker(e.target.value)} />
              </label>}
              <label>Output quantity unit
                <select value={quantityOutputUnit} onChange={(e) => setQuantityOutputUnit(e.target.value as "source" | "piece")}>
                  <option value="source">Source unit (cases remain cases)</option>
                  <option value="piece">Pieces (convert cases using pieces per case)</option>
                </select>
              </label>
              <PalletEditor value={palletization} products={products} onChange={setPalletization} />
            </div>
          )}
          {format !== "order_sheet" && <>
          <div className="section-heading">
            <div>
              <div className="eyebrow">COLUMNS</div>
              <h3>Field mappings</h3>
            </div>
            <button
              className="button"
              type="button"
              onClick={() => setMappings((items) => [...items, blankMapping()])}
            >
              + Add mapping
            </button>
          </div>
          <div className="mapping-list">
            {mappings.map((m, i) => (
              <div className="mapping-row" key={i}>
                <span className="mapping-order">{i + 1}</span>
                <label>
                  Output column
                  <input
                    value={m.output_column_name}
                    onChange={(e) =>
                      update(i, { output_column_name: e.target.value })
                    }
                    required
                  />
                </label>
                <label>
                  Type
                  <select
                    value={m.mapping_type}
                    onChange={(e) =>
                      update(i, {
                        mapping_type: e.target.value as Mapping["mapping_type"],
                      })
                    }
                  >
                    <option value="source_field">Source field</option>
                    <option value="constant">Constant</option>
                  </select>
                </label>
                {m.mapping_type === "source_field" ? (
                  <label>
                    Source field
                    <select
                      value={m.source_field || ""}
                      onChange={(e) =>
                        update(i, { source_field: e.target.value })
                      }
                      required
                    >
                      <option value="">Select field</option>
                      {Object.entries(fields).map(([key, label]) => (
                        <option key={key} value={key}>
                          {key} — {label}
                        </option>
                      ))}
                    </select>
                  </label>
                ) : (
                  <label>
                    Constant
                    <input
                      value={m.constant_value || ""}
                      onChange={(e) =>
                        update(i, { constant_value: e.target.value })
                      }
                      required
                    />
                  </label>
                )}
                <div className="mapping-actions">
                  <button
                    type="button"
                    className="icon-button"
                    onClick={() => move(i, -1)}
                    disabled={i === 0}
                    aria-label={`Move mapping ${i + 1} up`}
                  >
                    ↑
                  </button>
                  <button
                    type="button"
                    className="icon-button"
                    onClick={() => move(i, 1)}
                    disabled={i === mappings.length - 1}
                    aria-label={`Move mapping ${i + 1} down`}
                  >
                    ↓
                  </button>
                  <button
                    type="button"
                    className="icon-button"
                    onClick={() =>
                      setMappings((items) => items.filter((_, j) => j !== i))
                    }
                    disabled={mappings.length === 1}
                    aria-label={`Remove mapping ${i + 1}`}
                  >
                    ×
                  </button>
                </div>
              </div>
            ))}
          </div>
          </>}
          <div className="modal-actions">
            <button
              className="button"
              type="button"
              onClick={onClose}
              disabled={busy}
            >
              Cancel
            </button>
            <button className="button primary" disabled={busy}>
              {busy ? <Spinner /> : "Save profile"}
            </button>
          </div>
        </form>
      </section>
    </div>
  );
}

export function ProfilesPage() {
  const { companyId } = useCompany();
  const {
    data: profiles,
    error,
    loading,
    refresh,
  } = useAsync(
    () => (companyId ? getProfiles(companyId) : Promise.resolve([])),
    [companyId],
  );
  const { data: fields } = useAsync(getSourceFields, []);
  const [editing, setEditing] = useState<ExportProfile | null | undefined>(
    undefined,
  );
  useEffect(() => setEditing(undefined), [companyId]);
  const [actionError, setActionError] = useState("");
  const remove = async (p: ExportProfile) => {
    if (!window.confirm(`Delete export profile "${p.name}"?`)) return;
    setActionError("");
    try {
      await deleteProfile(p.id);
      await refresh();
    } catch (e) {
      setActionError((e as Error).message);
    }
  };
  const createOrderSheet = async () => {
    if (!companyId) return;
    setActionError("");
    try {
      await createProfile({
        company_id: companyId,
        name: "OrderMind 4-column order sheet",
        format: "order_sheet",
        delimiter: ",",
        encoding: "utf-8-sig",
        include_header: false,
        mappings: [],
        bonus_separate_row: false,
        bonus_marker: null,
        quantity_output_unit: "source",
        convert_case_using_pieces_per_case: false,
      });
      await refresh();
    } catch (e) {
      setActionError((e as Error).message);
    }
  };
  return (
    <>
      <div className="page-head">
        <div>
          <div className="eyebrow">SETUP / OUTPUT</div>
          <h1>Export profiles</h1>
          <p>Map approved order data to your receiving format.</p>
        </div>
        <div className="row-actions">
          <button className="button" onClick={() => void createOrderSheet()} disabled={!companyId || !!profiles?.some((p) => p.format === "order_sheet")}>
            + 4-column order sheet
          </button>
          <button className="button primary" onClick={() => setEditing(null)} disabled={!companyId}>
            + Create profile
          </button>
        </div>
      </div>
      <Alert message={error || actionError} />
      <section className="panel">
        {loading ? (
          <div className="center">
            <Spinner />
          </div>
        ) : !profiles?.length ? (
          <Empty>
            No export profiles yet. Create one to enable order downloads.
          </Empty>
        ) : (
          <div className="table-scroll">
            <table>
              <thead>
                <tr>
                  <th>Name</th>
                  <th>Format</th>
                  <th>Mappings</th>
                  <th>Actions</th>
                </tr>
              </thead>
              <tbody>
                {profiles.map((p) => (
                  <tr key={p.id}>
                    <td>
                      <strong>{p.name}</strong>
                      {p.palletization?.enabled && <small style={{ display: "block" }}>
                        Pallets: {p.palletization.dedicated_groups.length} dedicated groups ·
                        {p.palletization.automatic_pallets.max_weight_kg ? ` ${p.palletization.automatic_pallets.max_weight_kg} kg` : ""}
                        {p.palletization.automatic_pallets.max_rows ? ` · ${p.palletization.automatic_pallets.max_rows} ${p.palletization.automatic_pallets.row_count_mode.replaceAll("_", " ")}` : ""}
                        {` · ${p.palletization.output.layout.replaceAll("_", " ")}`}
                      </small>}
                    </td>
                    <td>{p.format.toUpperCase()}</td>
                    <td>{p.field_mappings.length}</td>
                    <td>
                      <div className="row-actions">
                        <button
                          className="text-button"
                          onClick={() => setEditing(p)}
                        >
                          Edit
                        </button>
                        <button
                          className="text-button danger"
                          onClick={() => void remove(p)}
                        >
                          Delete
                        </button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
      {editing !== undefined && companyId && fields && (
        <ProfileEditor
          companyId={companyId}
          profile={editing}
          fields={fields}
          onClose={() => setEditing(undefined)}
          onSave={refresh}
        />
      )}
    </>
  );
}
