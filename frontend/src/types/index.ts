export type Company = { id: number; name: string };
export type Customer = {
  id: number;
  company_id: number;
  customer_code: string;
  customer_name: string;
  email: string | null;
  phone: string | null;
  active: boolean;
};
export type Product = {
  id: number;
  company_id: number;
  sku: string;
  description: string;
  barcode: string | null;
  unit: string;
  active: boolean;
  packagings: {
    id: number;
    package_type: string;
    pieces_per_case: number;
    unit: string;
    package_code: string | null;
    packaging_barcode: string | null;
  }[];
};
export type ProductBrief = Pick<
  Product,
  "id" | "sku" | "description" | "barcode"
>;
export type Candidate = {
  id: number;
  product_id: number;
  rank: number;
  match_type: string;
  score: number;
  explanation: string;
  product: ProductBrief | null;
};
export type OrderLine = {
  id: number;
  line_number: number;
  original_text: string;
  product_phrase: string;
  requested_quantity: number;
  requested_unit: string;
  raw_unit?: string | null;
  unit_explicit?: boolean;
  quantity_text?: string | null;
  bonus_quantity?: number;
  final_bonus_quantity?: number | null;
  matched_product_id: number | null;
  matched_product: ProductBrief | null;
  final_sku: string | null;
  final_quantity: number | null;
  final_unit: string | null;
  order_sheet_paid_quantity?: number | null;
  order_sheet_bonus_quantity?: number | null;
  order_sheet_unit?: string | null;
  order_sheet_bonus_marker?: string | null;
  order_sheet_conversion_error?: string | null;
  confidence_score: number;
  confidence_reasons: string[];
  status: string;
  candidates: Candidate[];
};
export type ExportRecord = {
  id: number;
  export_profile_id: number | null;
  filename: string;
  format: string;
  created_at: string;
};
export type Order = {
  id: number;
  company_id: number;
  customer_id: number;
  customer: Pick<Customer, "id" | "customer_code" | "customer_name"> | null;
  order_number: string;
  status: string;
  overall_confidence: number;
  raw_input: string;
  created_at: string;
  approved_at: string | null;
  exported_at: string | null;
  last_export_profile_id: number | null;
  export_records: ExportRecord[];
  lines: OrderLine[];
};
export type OrderSummary = Pick<
  Order,
  | "id"
  | "company_id"
  | "customer_id"
  | "customer"
  | "order_number"
  | "status"
  | "overall_confidence"
  | "created_at"
  | "approved_at"
  | "exported_at"
  | "last_export_profile_id"
> & { line_count: number };
export type Mapping = {
  column_order: number;
  output_column_name: string;
  mapping_type: "source_field" | "constant";
  source_field: string | null;
  constant_value: string | null;
};
export type ExportProfile = {
  id: number;
  company_id: number;
  name: string;
  format: string;
  delimiter: string;
  encoding: string;
  include_header: boolean;
  bonus_separate_row: boolean;
  bonus_marker: string | null;
  quantity_output_unit: "source" | "piece";
  convert_case_using_pieces_per_case: boolean;
  field_mappings: (Mapping & { id: number })[];
};
