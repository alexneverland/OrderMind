import { expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { CustomersPage, ProductsPage } from "./CatalogPages";

vi.mock("../components/AppShell", () => ({
  useCompany: () => ({
    companyId: null,
    companies: [],
    companiesLoading: false,
    addCompany: vi.fn(),
  }),
}));
vi.mock("../api/masterData", () => ({
  getCustomers: vi.fn(),
  getProducts: vi.fn(),
}));
vi.mock("../api/orders", () => ({
  getOrders: vi.fn().mockResolvedValue([]),
  getOrderStats: vi.fn().mockResolvedValue({}),
}));

it("shows company creation on the empty Customers screen", () => {
  render(<CustomersPage />);
  expect(
    screen.getByText(/Create your first company to import customers/),
  ).toBeVisible();
  expect(screen.getByRole("button", { name: "Create company" })).toBeVisible();
  expect(
    screen.getByRole("heading", { name: "Import customers from Excel" }),
  ).toBeVisible();
  expect(
    screen.getByRole("button", { name: "Preview columns" }),
  ).toBeDisabled();
});

it("shows company creation on the empty Products screen", () => {
  render(<ProductsPage />);
  expect(
    screen.getByText(/Create your first company to import products/),
  ).toBeVisible();
  expect(screen.getByRole("button", { name: "Create company" })).toBeVisible();
  expect(
    screen.getByRole("heading", { name: "Import products from Excel" }),
  ).toBeVisible();
  expect(
    screen.getByRole("heading", { name: "Import packaging from Excel" }),
  ).toBeVisible();
  for (const button of screen.getAllByRole("button", {
    name: "Preview columns",
  })) {
    expect(button).toBeDisabled();
  }
});
