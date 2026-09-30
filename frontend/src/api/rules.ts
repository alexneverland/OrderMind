import { request } from "./client";
import type { PalletConfig } from "../types";

export type Unit = "piece" | "case" | "kg" | "pallet";
export type TriggerMode = "greater_than" | "greater_or_equal" | "per_quantity";
export type QuantityBonusConfig = {
  trigger: { mode: TriggerMode; quantity: number; unit: Unit };
  reward: { quantity: number; unit: Unit };
};
export type CompanyRule = {
  id: number;
  company_id: number;
  rule_type: "quantity_bonus";
  enabled: boolean;
  product_id: number | null;
  customer_id: number | null;
  configuration: QuantityBonusConfig;
};
export type Candidate = { id: number; label: string };
export type ProposedQuantityRule = {
  configuration: QuantityBonusConfig;
  product_reference: string | null;
  customer_reference: string | null;
  product_id: number | null;
  customer_id: number | null;
  product_candidates: Candidate[];
  customer_candidates: Candidate[];
};
export type RulesProposal = {
  settings_patch: Record<string, boolean | string | null>;
  quantity_rules: ProposedQuantityRule[];
  export_patch: {
    profile_id?: number | null;
    bonus_separate_row?: boolean;
    bonus_marker?: string | null;
    quantity_output_unit?: "source" | "piece";
    convert_case_using_pieces_per_case?: boolean;
    palletization?: Omit<PalletConfig, "dedicated_groups"> & {
      dedicated_groups: { name: string; products: { reference: string; product_id: number | null; candidates: Candidate[] }[] }[];
    };
  } | null;
  export_profile_candidates: Candidate[];
  unsupported_rules: { text: string; reason: string }[];
};

export const getCompanyRules = (companyId: number) =>
  request<CompanyRule[]>(`/companies/${companyId}/rules`);
export const analyzeRules = (companyId: number, description: string) =>
  request<RulesProposal>(`/companies/${companyId}/rules/analyze`, {
    method: "POST", body: JSON.stringify({ description }),
  });
export const applyRules = (companyId: number, proposal: RulesProposal) =>
  request<{ settings: import("./businessSettings").BusinessSettings; rules: CompanyRule[] }>(
    `/companies/${companyId}/rules/apply-proposal`, {
      method: "POST", body: JSON.stringify({ proposal }),
    },
  );
export const createRule = (companyId: number, payload: Omit<CompanyRule, "id" | "company_id">) =>
  request<CompanyRule>(`/companies/${companyId}/rules`, {
    method: "POST", body: JSON.stringify(payload),
  });
export const updateRule = (companyId: number, ruleId: number, payload: Partial<Omit<CompanyRule, "id" | "company_id" | "rule_type">>) =>
  request<CompanyRule>(`/companies/${companyId}/rules/${ruleId}`, {
    method: "PUT", body: JSON.stringify(payload),
  });
export const disableRule = (companyId: number, ruleId: number) =>
  request<void>(`/companies/${companyId}/rules/${ruleId}`, { method: "DELETE" });
