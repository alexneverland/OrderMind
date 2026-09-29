import { afterEach, expect, it, vi } from "vitest";
import { importExcel, previewExcel } from "./imports";

afterEach(() => vi.unstubAllGlobals());

it("sends Excel previews and imports as browser-managed multipart forms", async () => {
  const fetchMock = vi.fn().mockImplementation(() =>
    Promise.resolve(
      new Response(JSON.stringify({ available_columns: [] }), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    ),
  );
  vi.stubGlobal("fetch", fetchMock);
  const file = new File(["workbook"], "customers.xlsx");

  await previewExcel("customers", file);
  const [previewUrl, previewOptions] = fetchMock.mock.calls[0];
  expect(previewUrl).toBe("/api/v1/imports/preview");
  expect(previewOptions.headers).not.toHaveProperty("Content-Type");
  expect(previewOptions.body).toBeInstanceOf(FormData);
  expect(previewOptions.body.get("entity_type")).toBe("customers");
  expect(previewOptions.body.get("file")).toBe(file);

  await importExcel("customers", 7, file, { customer_code: "Code" });
  const [importUrl, importOptions] = fetchMock.mock.calls[1];
  expect(importUrl).toBe("/api/v1/imports/customers");
  expect(importOptions.headers).not.toHaveProperty("Content-Type");
  expect(importOptions.body.get("company_id")).toBe("7");
  expect(importOptions.body.get("mapping")).toBe('{"customer_code":"Code"}');

  await importExcel("packaging", 7, file, { product_sku: "SKU" });
  const [packagingUrl, packagingOptions] = fetchMock.mock.calls[2];
  expect(packagingUrl).toBe("/api/v1/imports/packaging");
  expect(packagingOptions.body.get("company_id")).toBe("7");
});
