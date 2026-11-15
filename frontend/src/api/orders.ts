import { download, request } from "./client";
import type { Order, OrderSummary } from "../types";

export const getOrders = (
  params: {
    companyId?: number;
    status?: string;
    search?: string;
    limit?: number;
    offset?: number;
  } = {},
) => {
  const query = new URLSearchParams();
  if (params.companyId) query.set("company_id", String(params.companyId));
  if (params.status) query.set("status", params.status);
  if (params.search) query.set("search", params.search);
  if (params.limit) query.set("limit", String(params.limit));
  if (params.offset) query.set("offset", String(params.offset));
  return request<OrderSummary[]>(`/orders?${query}`);
};
export type OrderStats = {
  pending_review: number;
  approved_today: number;
  exported_today: number;
  needs_attention: number;
};
export const getOrderStats = (companyId?: number) => {
  const now = new Date();
  const start = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  const end = new Date(now.getFullYear(), now.getMonth(), now.getDate() + 1);
  const query = new URLSearchParams({
    day_start: start.toISOString(),
    day_end: end.toISOString(),
  });
  if (companyId) query.set("company_id", String(companyId));
  return request<OrderStats>(`/orders/summary?${query}`);
};
export const getOrder = (id: number, profileId?: number) =>
  request<Order>(`/orders/${id}${profileId ? `?profile_id=${profileId}` : ""}`);
export type OrderFilePreview = {
  filename: string;
  text: string;
  method: "text" | "spreadsheet" | "document" | "pdf" | "ocr";
};
export type OrderFilePreviewJob = {
  job_id: string;
  status: "pending" | "processing" | "completed" | "failed";
  filename: string | null;
  text: string | null;
  method: OrderFilePreview["method"] | null;
  error: string | null;
};
const ASYNC_PREVIEW_EXTENSIONS = new Set([".pdf", ".png", ".jpg", ".jpeg", ".webp"]);
const POLL_INTERVAL_MS = 800;
const POLL_TIMEOUT_MS = 180_000;

export const previewOrderFile = async (file: File): Promise<OrderFilePreview> => {
  const body = new FormData();
  body.append("file", file);
  const dot = file.name.lastIndexOf(".");
  const ext = dot >= 0 ? file.name.slice(dot).toLowerCase() : "";
  if (!ASYNC_PREVIEW_EXTENSIONS.has(ext)) {
    return request<OrderFilePreview>("/orders/file-preview", { method: "POST", body });
  }
  const job = await request<OrderFilePreviewJob>("/orders/file-preview/jobs", { method: "POST", body });
  const deadline = Date.now() + POLL_TIMEOUT_MS;
  let current = job;
  while (current.status === "pending" || current.status === "processing") {
    if (Date.now() > deadline) {
      throw new Error("File extraction timed out; please retry.");
    }
    await new Promise((resolve) => setTimeout(resolve, POLL_INTERVAL_MS));
    current = await request<OrderFilePreviewJob>(`/orders/file-preview/jobs/${encodeURIComponent(current.job_id)}`);
  }
  if (current.status === "failed") {
    throw new Error(current.error || "Could not read order file");
  }
  return {
    filename: current.filename || file.name,
    text: current.text || "",
    method: current.method || "ocr",
  };
};
export const createOrder = (
  payload: { company_id: number; customer_id: number; text: string },
  key: string,
) =>
  request<Order>("/orders/create-from-match", {
    method: "POST",
    headers: { "Idempotency-Key": key },
    body: JSON.stringify(payload),
  });
export const confirmLine = (order: Order, lineId: number) => {
  const line = order.lines.find((item) => item.id === lineId);
  if (!line?.matched_product_id)
    throw new Error("No matched product to confirm.");
  return request(`/orders/${order.id}/lines/${lineId}/confirm`, {
    method: "POST",
    body: JSON.stringify({
      customer_id: order.customer_id,
      product_id: line.matched_product_id,
      original_phrase: line.product_phrase,
    }),
  });
};
export const correctLine = (
  order: Order,
  lineId: number,
  productId: number,
  notes: string,
) => {
  const line = order.lines.find((item) => item.id === lineId);
  if (!line) throw new Error("Order line was not found.");
  return request(`/orders/${order.id}/lines/${lineId}/correct`, {
    method: "POST",
    body: JSON.stringify({
      customer_id: order.customer_id,
      suggested_product_id: line.matched_product_id,
      correct_product_id: productId,
      original_phrase: line.product_phrase,
      notes,
    }),
  });
};
export const updateFinalValues = (
  orderId: number,
  lineId: number,
  quantity: number,
  unit: string,
  bonusQuantity?: number,
) =>
  request(`/orders/${orderId}/lines/${lineId}`, {
    method: "PATCH",
    body: JSON.stringify({ final_quantity: quantity, final_unit: unit, final_bonus_quantity: bonusQuantity }),
  });
export const approveOrder = (id: number) =>
  request(`/orders/${id}/approve`, { method: "POST" });
export const createOrderRevision = (id: number, companyId: number, requestId: string) =>
  request<Order>(`/orders/${id}/revisions`, {
    method: "POST", body: JSON.stringify({ company_id: companyId, request_id: requestId }),
  });
export const recheckOrderRevision = (id: number, companyId: number) =>
  request<Order>(`/orders/${id}/revision-review?company_id=${companyId}`, { method: "POST" });
export const confirmSafeLines = (order: Order) =>
  request<{ confirmed_count: number; skipped: { line_id: number; line_number: number; reason: string }[]; version: number }>(
    `/orders/${order.id}/confirm-safe?company_id=${order.company_id}&expected_version=${order.version}`, { method: "POST" },
  );
export const exportOrder = (orderId: number, profileId: number) =>
  download(`/orders/${orderId}/export/${profileId}`);
export type PalletPreview = {
  row_count_mode: "output_rows" | "logical_product_lines";
  layout: string;
  pallets: {
    pallet_number: number; type: "dedicated" | "automatic"; group_name: string | null;
    total_weight_kg: string | null; row_count: number; warnings: string[];
    items: { source_order_line_id: number; sku: string; description: string; paid_quantity: string; bonus_quantity: string; unit: string; weight_kg: string | null; output_row_count: number }[];
  }[];
};
export const getPalletPreview = (orderId: number, profileId: number) =>
  request<PalletPreview>(`/orders/${orderId}/pallet-preview/${profileId}`);
