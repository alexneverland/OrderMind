import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { OrderReviewPage } from "./OrderReviewPage";
import type { Order } from "../types";

const mock = vi.hoisted(() => ({
  getOrder: vi.fn(),
  confirmLine: vi.fn(),
  correctLine: vi.fn(),
  updateFinalValues: vi.fn(),
  approveOrder: vi.fn(),
  exportOrder: vi.fn(),
  getProducts: vi.fn(),
  getProfiles: vi.fn(),
  saveDownload: vi.fn(),
}));
vi.mock("../api/orders", () => ({
  getOrder: mock.getOrder,
  confirmLine: mock.confirmLine,
  correctLine: mock.correctLine,
  updateFinalValues: mock.updateFinalValues,
  approveOrder: mock.approveOrder,
  exportOrder: mock.exportOrder,
}));
vi.mock("../api/masterData", () => ({ getProducts: mock.getProducts }));
vi.mock("../api/exportProfiles", () => ({ getProfiles: mock.getProfiles }));
vi.mock("../api/client", () => ({ saveDownload: mock.saveDownload }));

const baseOrder = (): Order => ({
  id: 1,
  company_id: 3,
  customer_id: 4,
  customer: { id: 4, customer_code: "C-4", customer_name: "Deli" },
  order_number: "OM-1",
  status: "pending_review",
  overall_confidence: 0.81,
  raw_input: "10 κοκκινα\n5 σαλαμια",
  created_at: "2026-09-28T10:00:00",
  approved_at: null,
  exported_at: null,
  last_export_profile_id: null,
  export_records: [],
  lines: [
    {
      id: 7,
      line_number: 1,
      original_text: "10 κοκκινα",
      product_phrase: "κοκκινα",
      requested_quantity: 10,
      requested_unit: "piece",
      matched_product_id: 9,
      matched_product: {
        id: 9,
        sku: "7843",
        description: "Smoked turkey",
        barcode: null,
      },
      final_sku: "7843",
      final_quantity: 10,
      final_unit: "piece",
      confidence_score: 0.81,
      confidence_reasons: ["Customer alias match"],
      status: "needs_review",
      candidates: [
        {
          id: 1,
          product_id: 9,
          rank: 1,
          match_type: "customer_alias",
          score: 0.81,
          explanation: "Alias",
          product: {
            id: 9,
            sku: "7843",
            description: "Smoked turkey",
            barcode: null,
          },
        },
      ],
    },
  ],
});
let current: Order;
const show = () =>
  render(
    <MemoryRouter initialEntries={["/orders/1"]}>
      <Routes>
        <Route path="/orders/:orderId" element={<OrderReviewPage />} />
      </Routes>
    </MemoryRouter>,
  );

beforeEach(() => {
  vi.clearAllMocks();
  vi.spyOn(window, "scrollBy").mockImplementation(() => {});
  current = baseOrder();
  mock.getOrder.mockImplementation(async () => structuredClone(current));
  mock.getProfiles.mockResolvedValue([
    { id: 12, name: "SoftOne", format: "xlsx" },
  ]);
  mock.getProducts.mockResolvedValue([
    {
      id: 10,
      company_id: 3,
      sku: "100",
      description: "Salami",
      barcode: "123",
      unit: "piece",
      active: true,
    },
  ]);
  mock.confirmLine.mockImplementation(async () => {
    current.lines[0].status = "confirmed";
  });
  mock.correctLine.mockImplementation(async () => {
    current.lines[0].status = "corrected";
    current.lines[0].matched_product_id = 10;
  });
  mock.approveOrder.mockImplementation(async () => {
    current.status = "approved";
    current.approved_at = "2026-09-28T11:00:00";
  });
  mock.exportOrder.mockResolvedValue({
    blob: new Blob(["x"]),
    filename: "order.xlsx",
  });
  vi.spyOn(window, "confirm").mockReturnValue(true);
});
afterEach(() => vi.restoreAllMocks());

describe("operator review", () => {
  it("renders verbatim raw input, match and review status", async () => {
    show();
    expect(await screen.findByText("Smoked turkey")).toBeInTheDocument();
    expect(document.querySelector(".raw-panel pre")?.textContent).toBe(
      "10 κοκκινα\n5 σαλαμια",
    );
    expect(screen.getAllByText("Needs review").length).toBeGreaterThan(0);
    expect(screen.getByText("SKU 7843")).toBeInTheDocument();
    fireEvent.click(screen.getByText("Why this match?"));
    expect(screen.getByText("Customer alias match")).toBeInTheDocument();
  });
  it("shows missing customer unit separately from the operator final unit", async () => {
    current.lines[0].requested_unit = "unknown";
    current.lines[0].unit_explicit = false;
    current.lines[0].final_unit = null;
    show();
    expect(await screen.findByText("10 · unit not specified")).toBeInTheDocument();
    expect(screen.getByText("10 · unit not set")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Edit final values" }));
    expect(screen.getByRole("combobox", { name: "Final unit" })).toHaveValue("unknown");
    expect(screen.getByRole("button", { name: "Save values" })).toBeDisabled();
    fireEvent.change(screen.getByRole("combobox", { name: "Final unit" }), { target: { value: "piece" } });
    expect(screen.getByRole("button", { name: "Save values" })).toBeEnabled();
  });
  it("shows customer bonus, calculated promotion and final bonus separately", async () => {
    current.lines[0].bonus_quantity = 2;
    current.lines[0].calculated_bonus_quantity = 1;
    current.lines[0].promotion_result = {
      applied_rule_id: 7, calculated_bonus_quantity: 1,
      explanation: "Rule #7: Every 10 piece gives 1 free piece.",
      requires_review: true, matching_rule_ids: [7],
    };
    show();
    expect(await screen.findByText(/Rule #7: Every 10 piece/)).toBeInTheDocument();
    expect(screen.getByText(/Review required: choose the final free quantity/)).toBeInTheDocument();
    expect(screen.getAllByText((_, element) => element?.tagName === "SMALL" && /\+\s*2\s*δώρο/.test(element.textContent || "")).length).toBeGreaterThan(0);
    expect(screen.getByText((_, element) => element?.tagName === "STRONG" && /\+1 piece free/.test(element.textContent || ""))).toBeInTheDocument();
  });
  it("does not freeze an automatic bonus when only paid quantity changes", async () => {
    current.lines[0].calculated_bonus_quantity = 1;
    current.lines[0].promotion_result = {
      applied_rule_id: 7, calculated_bonus_quantity: 1,
      explanation: "Every 10 pieces gives 1 free.", requires_review: false, matching_rule_ids: [7],
    };
    mock.updateFinalValues.mockResolvedValue({});
    show();
    fireEvent.click(await screen.findByRole("button", { name: "Edit final values" }));
    fireEvent.change(screen.getByRole("spinbutton", { name: "Final quantity" }), { target: { value: "20" } });
    fireEvent.click(screen.getByRole("button", { name: "Save values" }));
    await waitFor(() => expect(mock.updateFinalValues).toHaveBeenCalledWith(1, 7, 20, "piece", undefined));
  });
  it("keeps the current line mounted and restores its viewport position after save", async () => {
    let top = 180;
    const rectSpy = vi.spyOn(HTMLElement.prototype, "getBoundingClientRect").mockImplementation(function (this: HTMLElement) {
      const y = this.hasAttribute("data-order-line-id") ? top : 0;
      return { x: 0, y, top: y, left: 0, bottom: y + 100, right: 100,
        width: 100, height: 100, toJSON: () => ({}) } as DOMRect;
    });
    mock.updateFinalValues.mockImplementation(async () => {
      current.lines[0].final_quantity = 20;
    });
    mock.getOrder.mockImplementation(async () => {
      if (current.lines[0].final_quantity === 20) top = 70;
      return structuredClone(current);
    });
    show();
    const card = (await screen.findByText("Smoked turkey")).closest("[data-order-line-id]");
    fireEvent.click(screen.getByRole("button", { name: "Edit final values" }));
    fireEvent.change(screen.getByRole("spinbutton", { name: "Final quantity" }), { target: { value: "20" } });
    fireEvent.click(screen.getByRole("button", { name: "Save values" }));
    await waitFor(() => expect(card?.textContent).toContain("20 piece"));
    expect(card).toBe(document.querySelector('[data-order-line-id="7"]'));
    expect(window.scrollBy).toHaveBeenCalledWith(0, -110);
    rectSpy.mockRestore();
  });
  it("resets the bonus editor after recalculation and does not resend a stale bonus", async () => {
    current.lines[0].calculated_bonus_quantity = 1;
    current.lines[0].final_bonus_quantity = 3;
    current.lines[0].promotion_result = {
      applied_rule_id: 7, calculated_bonus_quantity: 1,
      explanation: "One free piece.", requires_review: false, matching_rule_ids: [7],
    };
    mock.updateFinalValues.mockImplementation(async (_orderId, _lineId, quantity) => {
      current.lines[0].final_quantity = quantity;
      current.lines[0].calculated_bonus_quantity = quantity === 20 ? 2 : 3;
      current.lines[0].final_bonus_quantity = null;
      current.lines[0].promotion_result = {
        applied_rule_id: 7, calculated_bonus_quantity: current.lines[0].calculated_bonus_quantity,
        explanation: "Updated free pieces.", requires_review: false, matching_rule_ids: [7],
      };
    });
    show();
    fireEvent.click(await screen.findByRole("button", { name: "Edit final values" }));
    fireEvent.change(screen.getByRole("spinbutton", { name: "Final quantity" }), { target: { value: "20" } });
    fireEvent.click(screen.getByRole("button", { name: "Save values" }));
    await waitFor(() => expect(mock.updateFinalValues).toHaveBeenCalledWith(1, 7, 20, "piece", undefined));
    await screen.findByText("Updated free pieces.");
    fireEvent.click(screen.getByRole("button", { name: "Edit final values" }));
    expect(screen.getByRole("spinbutton", { name: "Ποσότητα δώρου" })).toHaveValue(2);
    fireEvent.change(screen.getByRole("spinbutton", { name: "Final quantity" }), { target: { value: "30" } });
    fireEvent.click(screen.getByRole("button", { name: "Save values" }));
    await waitFor(() => expect(mock.updateFinalValues).toHaveBeenLastCalledWith(1, 7, 30, "piece", undefined));
  });
  it("sends a bonus edited alongside a new quantity as a fresh choice", async () => {
    current.lines[0].calculated_bonus_quantity = 2;
    current.lines[0].final_bonus_quantity = 3;
    show();
    fireEvent.click(await screen.findByRole("button", { name: "Edit final values" }));
    fireEvent.change(screen.getByRole("spinbutton", { name: "Final quantity" }), { target: { value: "40" } });
    fireEvent.change(screen.getByRole("spinbutton", { name: "Ποσότητα δώρου" }), { target: { value: "5" } });
    fireEvent.click(screen.getByRole("button", { name: "Save values" }));
    await waitFor(() => expect(mock.updateFinalValues).toHaveBeenCalledWith(1, 7, 40, "piece", 5));
  });
  it("shows paid and free quantities that the four-column export will receive", async () => {
    mock.getProfiles.mockResolvedValue([
      { id: 20, name: "Legacy sheet", format: "order_sheet", bonus_marker: "Α" },
    ]);
    current.lines[0].requested_quantity = 10;
    current.lines[0].requested_unit = "case";
    current.lines[0].bonus_quantity = 1;
    current.lines[0].final_quantity = 10;
    current.lines[0].final_unit = "case";
    current.lines[0].order_sheet_paid_quantity = 100;
    current.lines[0].order_sheet_bonus_quantity = 10;
    current.lines[0].order_sheet_unit = "piece";
    current.lines[0].order_sheet_bonus_marker = "Α";
    show();
    expect(await screen.findByText("100 τεμάχια")).toBeInTheDocument();
    expect(screen.getByText("+ 10 τεμάχια δώρο (χωριστή γραμμή Α)")).toBeInTheDocument();
    await waitFor(() => expect(mock.getOrder).toHaveBeenCalledWith(1, 20));
  });
  it("confirms a line and refreshes its status", async () => {
    show();
    fireEvent.click(
      await screen.findByRole("button", { name: "Confirm match" }),
    );
    await waitFor(() =>
      expect(mock.confirmLine).toHaveBeenCalledWith(
        expect.objectContaining({ id: 1 }),
        7,
      ),
    );
    expect(await screen.findByText("Confirmed")).toBeInTheDocument();
  });
  it("searches company products and sends correction", async () => {
    show();
    fireEvent.click(
      await screen.findByRole("button", { name: "Change product" }),
    );
    const dialog = screen.getByRole("dialog");
    fireEvent.change(
      within(dialog).getByRole("textbox", { name: "Search products" }),
      { target: { value: "100" } },
    );
    fireEvent.click(within(dialog).getByRole("button", { name: "Search" }));
    fireEvent.click(await within(dialog).findByRole("radio"));
    fireEvent.click(
      within(dialog).getByRole("button", { name: "Correct match" }),
    );
    await waitFor(() =>
      expect(mock.getProducts).toHaveBeenCalledWith(3, "100"),
    );
    await waitFor(() =>
      expect(mock.correctLine).toHaveBeenCalledWith(
        expect.objectContaining({ id: 1 }),
        7,
        10,
        "",
      ),
    );
  });
  it("blocks approval while a line needs review", async () => {
    show();
    expect(
      await screen.findByRole("button", { name: "Approve order" }),
    ).toBeDisabled();
    expect(mock.approveOrder).not.toHaveBeenCalled();
  });
  it("approves ready lines and removes edit controls", async () => {
    current.lines[0].status = "confirmed";
    show();
    fireEvent.click(
      await screen.findByRole("button", { name: "Approve order" }),
    );
    expect(
      screen.getByRole("dialog", { name: "Approve order" }),
    ).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Confirm approval" }));
    await waitFor(() => expect(mock.approveOrder).toHaveBeenCalledWith(1));
    expect(await screen.findByText("Approved")).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Change product" }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Edit final values" }),
    ).not.toBeInTheDocument();
  });
  it("refreshes the order when approval recalculates a stale promotion", async () => {
    current.lines[0].status = "confirmed";
    mock.approveOrder.mockImplementationOnce(async () => {
      current.lines[0].calculated_bonus_quantity = 2;
      current.lines[0].promotion_result = {
        applied_rule_id: 7, calculated_bonus_quantity: 2,
        explanation: "Updated promotion: 2 free pieces.",
        requires_review: false, matching_rule_ids: [7],
      };
      throw new Error("Promotion was recalculated. Review before approving.");
    });
    show();
    fireEvent.click(await screen.findByRole("button", { name: "Approve order" }));
    fireEvent.click(screen.getByRole("button", { name: "Confirm approval" }));
    expect(await screen.findByText("Updated promotion: 2 free pieces.")).toBeInTheDocument();
    expect(screen.getByText("Promotion was recalculated. Review before approving.")).toBeInTheDocument();
    expect(mock.getOrder.mock.calls.length).toBeGreaterThan(1);
  });
  it("exports with a selected profile and triggers download", async () => {
    current.status = "approved";
    current.lines[0].status = "confirmed";
    show();
    const select = await screen.findByRole("combobox", {
      name: "Export profile",
    });
    await screen.findByRole("option", { name: "SoftOne · XLSX" });
    fireEvent.change(select, { target: { value: "12" } });
    fireEvent.click(screen.getByRole("button", { name: "Export & download" }));
    await waitFor(() => expect(mock.exportOrder).toHaveBeenCalledWith(1, 12));
    expect(mock.saveDownload).toHaveBeenCalledWith(
      expect.any(Blob),
      "order.xlsx",
    );
    expect(
      screen.queryByRole("button", { name: "Change product" }),
    ).not.toBeInTheDocument();
  });
});
