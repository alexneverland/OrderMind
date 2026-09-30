import { expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import { emptyPalletConfig, PalletEditor } from "./PalletEditor";
import type { Product } from "../types";

it("edits a dedicated group and both pallet capacities without changing product identity", () => {
  const onChange = vi.fn();
  const products = [{ id: 7, sku: "A", description: "Product A" }] as Product[];
  const config = { ...emptyPalletConfig(), enabled: true,
    dedicated_groups: [{ name: "Together", product_ids: [7] }],
    automatic_pallets: { max_weight_kg: 360, max_rows: 16, row_count_mode: "output_rows" as const, packing_strategy: "sequential" as const } };
  render(<PalletEditor value={config} products={products} onChange={onChange} />);
  fireEvent.click(screen.getByText("Products (1)"));
  expect(screen.getByRole("checkbox", { name: /A · Product A/ })).toBeChecked();
  expect(screen.getByRole("spinbutton", { name: "Maximum weight (kg)" })).toHaveValue(360);
  fireEvent.change(screen.getByRole("spinbutton", { name: "Maximum rows" }), { target: { value: "25" } });
  expect(onChange).toHaveBeenCalledWith(expect.objectContaining({
    automatic_pallets: expect.objectContaining({ max_rows: 25, max_weight_kg: 360 }),
    dedicated_groups: [{ name: "Together", product_ids: [7] }],
  }));
});
