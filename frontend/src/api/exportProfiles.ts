import { request } from "./client";
import type { ExportProfile, Mapping } from "../types";

export const getProfiles = (companyId?: number) =>
  request<ExportProfile[]>(
    `/export-profiles${companyId ? `?company_id=${companyId}` : ""}`,
  );
export const getSourceFields = () =>
  request<Record<string, string>>("/export-profiles/source-fields");
export type ProfileInput = {
  company_id: number;
  name: string;
  format: string;
  delimiter: string;
  encoding: string;
  include_header: boolean;
  mappings: Mapping[];
};
export const createProfile = (input: ProfileInput) =>
  request<ExportProfile>("/export-profiles", {
    method: "POST",
    body: JSON.stringify(input),
  });
export const updateProfile = (id: number, input: ProfileInput) =>
  request<ExportProfile>(`/export-profiles/${id}`, {
    method: "PUT",
    body: JSON.stringify(input),
  });
export const deleteProfile = (id: number) =>
  request<void>(`/export-profiles/${id}`, { method: "DELETE" });
