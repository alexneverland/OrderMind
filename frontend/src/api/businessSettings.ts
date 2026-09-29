import { request } from "./client";

export type BusinessSettings = {
  company_id: number;
  bonus_enabled: boolean;
  bonus_expression_mode: "disabled" | "paid_plus_bonus" | "explicit_only";
  unitless_order_behavior: "require_review" | "piece" | "product_master_unit" | "learned_product_preference";
  allow_packaging_conversion: boolean;
  learn_unit_preferences: boolean;
};

export const getBusinessSettings = (companyId: number) =>
  request<BusinessSettings>(`/companies/${companyId}/business-settings`);

export const saveBusinessSettings = (settings: BusinessSettings) =>
  request<BusinessSettings>(`/companies/${settings.company_id}/business-settings`, {
    method: "PUT",
    body: JSON.stringify(settings),
  });
