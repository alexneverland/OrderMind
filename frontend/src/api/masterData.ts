import { request } from "./client";
import type { Company, Customer, Product } from "../types";

export const getCompanies = () => request<Company[]>("/companies");
export const getCustomers = (companyId: number, search = "") =>
  request<Customer[]>(
    `/customers?company_id=${companyId}&search=${encodeURIComponent(search)}`,
  );
export const getProducts = (companyId: number, search = "") =>
  request<Product[]>(
    `/products?company_id=${companyId}&search=${encodeURIComponent(search)}`,
  );
export const createCompany = (name: string) =>
  request<Company>("/companies", {
    method: "POST",
    body: JSON.stringify({ name }),
  });
export const createCustomer = (payload: {
  company_id: number;
  customer_code: string;
  customer_name: string;
  email?: string;
  phone?: string;
}) =>
  request<Customer>("/customers", {
    method: "POST",
    body: JSON.stringify(payload),
  });
export const createProduct = (payload: {
  company_id: number;
  sku: string;
  description: string;
  barcode?: string;
    unit: string;
    kg_per_piece?: number | null;
}) =>
  request<Product>("/products", {
    method: "POST",
    body: JSON.stringify(payload),
  });
export const setProductWeight = (companyId: number, productId: number, kgPerPiece: number | null) =>
  request<Product>(`/products/${productId}/physical-weight`, {
    method: "PUT", body: JSON.stringify({ company_id: companyId, kg_per_piece: kgPerPiece }),
  });
export const setPackagingWeight = (companyId: number, packagingId: number, kgPerCase: number | null) =>
  request(`/products/packaging/${packagingId}/physical-weight`, {
    method: "PUT", body: JSON.stringify({ company_id: companyId, kg_per_case: kgPerCase }),
  });
