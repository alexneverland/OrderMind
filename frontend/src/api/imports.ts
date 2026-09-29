import { request } from "./client";

export type ImportEntity = "customers" | "products" | "packaging";
export type ImportPreview = {
  entity_type: string;
  available_columns: string[];
  total_preview_rows: number;
  preview_rows: Record<string, unknown>[];
  suggested_mapping: Record<string, string>;
  supported_target_fields: string[];
  required_target_fields: string[];
};
export type ImportSummary = {
  entity_type: string;
  total_rows: number;
  imported: number;
  skipped: number;
  errors: number;
  error_details: { row_number: number; field: string | null; reason: string }[];
};

export function previewExcel(entity: ImportEntity, file: File) {
  const body = new FormData();
  body.append("entity_type", entity);
  body.append("file", file);
  return request<ImportPreview>("/imports/preview", { method: "POST", body });
}

export function importExcel(
  entity: ImportEntity,
  companyId: number,
  file: File,
  mapping: Record<string, string>,
) {
  const body = new FormData();
  body.append("company_id", String(companyId));
  body.append("mapping", JSON.stringify(mapping));
  body.append("file", file);
  return request<ImportSummary>(`/imports/${entity}`, { method: "POST", body });
}
