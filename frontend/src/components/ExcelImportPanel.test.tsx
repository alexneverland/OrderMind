import { beforeEach, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { ExcelImportPanel } from "./ExcelImportPanel";

const mock = vi.hoisted(() => ({
  previewExcel: vi.fn(),
  importExcel: vi.fn(),
}));
vi.mock("../api/imports", () => mock);

beforeEach(() => {
  vi.clearAllMocks();
  mock.previewExcel.mockResolvedValue({
    entity_type: "customers",
    available_columns: ["Code", "Name"],
    total_preview_rows: 2,
    preview_rows: [{ Code: "C1", Name: "Acme" }],
    suggested_mapping: { customer_code: "Code" },
    supported_target_fields: ["customer_code", "customer_name"],
    required_target_fields: ["customer_code", "customer_name"],
  });
  mock.importExcel.mockResolvedValue({
    entity_type: "customers",
    total_rows: 2,
    imported: 1,
    skipped: 0,
    errors: 1,
    error_details: [
      { row_number: 3, field: "customer_code", reason: "Duplicate code" },
    ],
  });
});

it("requires mapping, imports into the selected company, and reports row errors", async () => {
  const onImported = vi.fn().mockResolvedValue(undefined);
  render(
    <ExcelImportPanel
      id="customer-import"
      entity="customers"
      companyId={7}
      onImported={onImported}
    />,
  );
  const file = new File(["workbook"], "customers.xlsx");
  fireEvent.change(screen.getByLabelText("customers Excel file"), {
    target: { files: [file] },
  });
  fireEvent.click(screen.getByRole("button", { name: "Preview columns" }));
  await screen.findByText("Map Excel columns");
  expect(screen.getByRole("button", { name: "Import 2 rows" })).toBeDisabled();
  fireEvent.change(screen.getByRole("combobox", { name: "customer name" }), {
    target: { value: "Name" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Import 2 rows" }));
  await waitFor(() =>
    expect(mock.importExcel).toHaveBeenCalledWith("customers", 7, file, {
      customer_code: "Code",
      customer_name: "Name",
    }),
  );
  expect(
    await screen.findByText(/1 imported, 0 skipped, 1 errors/),
  ).toBeVisible();
  expect(screen.getByText(/Row 3.*Duplicate code/)).toBeVisible();
  expect(onImported).toHaveBeenCalledOnce();
});

it("keeps the import action unavailable when the file is too large", () => {
  render(
    <ExcelImportPanel
      id="product-import"
      entity="products"
      companyId={7}
      onImported={vi.fn()}
    />,
  );
  const file = new File([new Uint8Array(10_000_001)], "large.xlsx");
  fireEvent.change(screen.getByLabelText("products Excel file"), {
    target: { files: [file] },
  });
  expect(
    screen.getByRole("button", { name: "Preview columns" }),
  ).toBeDisabled();
  expect(screen.getByRole("alert")).toHaveTextContent("10 MB");
});

it("reports skipped packaging rows on a repeat import", async () => {
  mock.previewExcel.mockResolvedValue({
    entity_type: "packaging",
    available_columns: ["SKU", "Type", "Pieces"],
    total_preview_rows: 1,
    preview_rows: [{ SKU: "SKU-1", Type: "case", Pieces: "12" }],
    suggested_mapping: {
      product_sku: "SKU",
      package_type: "Type",
      pieces_per_case: "Pieces",
    },
    supported_target_fields: ["product_sku", "package_type", "pieces_per_case"],
    required_target_fields: ["product_sku", "package_type", "pieces_per_case"],
  });
  mock.importExcel.mockResolvedValue({
    entity_type: "packaging",
    total_rows: 1,
    imported: 0,
    skipped: 1,
    errors: 0,
    error_details: [],
  });
  render(
    <ExcelImportPanel
      id="packaging-import"
      entity="packaging"
      companyId={7}
      onImported={vi.fn().mockResolvedValue(undefined)}
    />,
  );
  const file = new File(["workbook"], "packaging.xlsx");
  fireEvent.change(screen.getByLabelText("packaging Excel file"), {
    target: { files: [file] },
  });
  fireEvent.click(screen.getByRole("button", { name: "Preview columns" }));
  await screen.findByRole("button", { name: "Import 1 row" });
  fireEvent.click(screen.getByRole("button", { name: "Import 1 row" }));
  await waitFor(() =>
    expect(mock.importExcel).toHaveBeenCalledWith("packaging", 7, file, {
      product_sku: "SKU",
      package_type: "Type",
      pieces_per_case: "Pieces",
    }),
  );
  expect(
    await screen.findByText(/0 imported, 1 skipped, 0 errors/),
  ).toBeVisible();
});
