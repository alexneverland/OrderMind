import { useState } from "react";
import {
  importExcel,
  previewExcel,
  type ImportEntity,
  type ImportPreview,
  type ImportSummary,
} from "../api/imports";
import { Alert, Spinner } from "./ui";

const MAX_UPLOAD_BYTES = 10_000_000;
const fieldLabel = (field: string) => field.replaceAll("_", " ");

export function ExcelImportPanel({
  id,
  entity,
  companyId,
  onImported,
}: {
  id: string;
  entity: ImportEntity;
  companyId: number | null;
  onImported: () => Promise<void>;
}) {
  const [file, setFile] = useState<File | null>(null);
  const [preview, setPreview] = useState<ImportPreview | null>(null);
  const [mapping, setMapping] = useState<Record<string, string>>({});
  const [summary, setSummary] = useState<ImportSummary | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const title =
    entity === "customers"
      ? "customers"
      : entity === "products"
        ? "products"
        : "packaging";

  const inspect = async () => {
    if (!companyId || !file || busy) return;
    setBusy(true);
    setError("");
    setPreview(null);
    setSummary(null);
    try {
      const result = await previewExcel(entity, file);
      setPreview(result);
      setMapping(result.suggested_mapping);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const submit = async () => {
    if (!companyId || !file || !preview || busy) return;
    setBusy(true);
    setError("");
    try {
      const result = await importExcel(entity, companyId, file, mapping);
      setSummary(result);
      setPreview(null);
      try {
        await onImported();
      } catch {
        setError(
          "Import completed, but the list could not refresh. Reload the page to see the imported rows.",
        );
      }
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const missingRequired =
    preview?.required_target_fields.some((field) => !mapping[field]) ?? true;

  return (
    <section id={id} className="panel padded import-panel">
      <h2>Import {title} from Excel</h2>
      <p>
        Upload an .xlsx file (up to 10 MB). Preview its columns, check the
        mapping, then import into the selected company.{" "}
        {entity === "packaging"
          ? "Import products first. Identical rows are skipped; changed package codes or barcodes appear as conflicts."
          : entity === "products"
            ? "Map gross kg per piece when available. Reimporting an existing SKU with this column updates only its trusted piece weight; other duplicates remain errors."
            : "Duplicate codes and invalid rows appear as errors below."}
      </p>
      {!companyId && (
        <p className="import-prerequisite">
          Create and select a company to enable Excel import.
        </p>
      )}
      <Alert message={error} />
      <div className="import-actions">
        <label>
          Excel file
          <input
            aria-label={`${title} Excel file`}
            type="file"
            accept=".xlsx"
            disabled={busy || !companyId}
            onChange={(e) => {
              const selected = e.target.files?.[0] ?? null;
              setFile(selected);
              setPreview(null);
              setSummary(null);
              setMapping({});
              setError(
                selected && selected.size > MAX_UPLOAD_BYTES
                  ? "Excel file exceeds the 10 MB limit."
                  : "",
              );
            }}
          />
        </label>
        <button
          type="button"
          className="button"
          disabled={!companyId || !file || file.size > MAX_UPLOAD_BYTES || busy}
          onClick={() => void inspect()}
        >
          {busy && !preview ? <Spinner /> : "Preview columns"}
        </button>
      </div>
      {preview && (
        <div className="import-preview">
          <h3>Map Excel columns</h3>
          <p>
            {preview.total_preview_rows} data rows found. Required fields are
            marked *.
          </p>
          <div className="import-mapping">
            {preview.supported_target_fields.map((field) => (
              <label key={field}>
                {fieldLabel(field)}
                {preview.required_target_fields.includes(field) ? " *" : ""}
                <select
                  aria-label={fieldLabel(field)}
                  value={mapping[field] || ""}
                  disabled={busy}
                  onChange={(e) =>
                    setMapping((current) => ({
                      ...current,
                      [field]: e.target.value,
                    }))
                  }
                >
                  <option value="">Do not import</option>
                  {preview.available_columns.map((column) => (
                    <option key={column} value={column}>
                      {column}
                    </option>
                  ))}
                </select>
              </label>
            ))}
          </div>
          <h3>Sample rows</h3>
          <div className="table-scroll">
            <table>
              <thead>
                <tr>
                  {preview.available_columns.map((column) => (
                    <th key={column}>{column}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {preview.preview_rows.map((row, index) => (
                  <tr key={index}>
                    {preview.available_columns.map((column) => (
                      <td key={column}>{String(row[column] ?? "")}</td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <button
            type="button"
            className="button primary"
            disabled={busy || missingRequired || !preview.total_preview_rows}
            onClick={() => void submit()}
          >
            {busy ? (
              <Spinner />
            ) : (
              `Import ${preview.total_preview_rows} ${preview.total_preview_rows === 1 ? "row" : "rows"}`
            )}
          </button>
          {missingRequired && <p>Map every required field before importing.</p>}
        </div>
      )}
      {summary && (
        <div className="import-summary" role="status">
          <h3>Import result</h3>
          <p>
            {summary.imported} imported, {summary.skipped} skipped,{" "}
            {summary.errors} errors out of {summary.total_rows} rows.
          </p>
          {!!summary.error_details.length && (
            <div className="import-errors">
              <strong>Row errors</strong>
              <ul>
                {summary.error_details.slice(0, 50).map((item, index) => (
                  <li key={`${item.row_number}-${index}`}>
                    Row {item.row_number}
                    {item.field ? ` (${fieldLabel(item.field)})` : ""}:{" "}
                    {item.reason}
                  </li>
                ))}
              </ul>
              {summary.error_details.length > 50 && (
                <p>
                  Showing the first 50 of {summary.error_details.length} errors.
                </p>
              )}
            </div>
          )}
        </div>
      )}
    </section>
  );
}
