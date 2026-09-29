import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { expect, it, vi } from "vitest";
import { NewOrderPage } from "./NewOrderPage";

const mock = vi.hoisted(() => ({
  companyId: 1,
  getCustomers: vi.fn(),
  createOrder: vi.fn(),
  previewOrderFile: vi.fn(),
}));
vi.mock("../components/AppShell", () => ({
  useCompany: () => ({
    companyId: mock.companyId,
    companies: [
      { id: 1, name: "One" },
      { id: 2, name: "Two" },
    ],
    setCompanyId: vi.fn(),
  }),
}));
vi.mock("../api/masterData", () => ({ getCustomers: mock.getCustomers }));
vi.mock("../api/orders", () => ({ createOrder: mock.createOrder, previewOrderFile: mock.previewOrderFile }));

it("discards a late customer response from the previous company", async () => {
  let resolveFirst!: (value: unknown[]) => void;
  mock.companyId = 1;
  mock.getCustomers.mockImplementation((id: number) =>
    id === 1
      ? new Promise((resolve) => {
          resolveFirst = resolve;
        })
      : Promise.resolve([
          { id: 22, customer_code: "B", customer_name: "Beta" },
        ]),
  );
  const { rerender } = render(
    <MemoryRouter>
      <NewOrderPage />
    </MemoryRouter>,
  );
  mock.companyId = 2;
  rerender(
    <MemoryRouter>
      <NewOrderPage />
    </MemoryRouter>,
  );
  await screen.findByRole("option", { name: "B — Beta" });
  await act(async () => {
    resolveFirst([{ id: 11, customer_code: "A", customer_name: "Alpha" }]);
  });
  expect(
    screen.queryByRole("option", { name: "A — Alpha" }),
  ).not.toBeInTheDocument();
  await waitFor(() => expect(mock.getCustomers).toHaveBeenCalledWith(2, ""));
});

it("previews uploaded text and submits the reviewed text through the normal order flow", async () => {
  mock.companyId = 1;
  mock.getCustomers.mockResolvedValue([{ id: 7, customer_code: "C7", customer_name: "Cafe" }]);
  mock.previewOrderFile.mockResolvedValue({ filename: "order.txt", text: "10 olives", method: "text" });
  mock.createOrder.mockResolvedValue({ id: 42 });
  render(<MemoryRouter><NewOrderPage /></MemoryRouter>);
  await screen.findByRole("option", { name: "C7 — Cafe" });
  fireEvent.change(screen.getByLabelText("Customer"), { target: { value: "7" } });
  fireEvent.change(screen.getByLabelText("Customer order file"), {
    target: { files: [new File(["10 olives"], "order.txt", { type: "text/plain" })] },
  });
  await waitFor(() => expect(screen.getByLabelText("Customer order text")).toHaveValue("10 olives"));
  fireEvent.change(screen.getByLabelText("Customer order text"), { target: { value: "12 olives" } });
  fireEvent.click(screen.getByRole("button", { name: "Parse & Match →" }));
  await waitFor(() => expect(mock.createOrder).toHaveBeenCalledWith(
    { company_id: 1, customer_id: 7, text: "12 olives" }, expect.any(String),
  ));
});

it("requires an operator to resolve unreadable handwriting before creating the order", async () => {
  mock.companyId = 1;
  mock.getCustomers.mockResolvedValue([{ id: 7, customer_code: "C7", customer_name: "Cafe" }]);
  mock.previewOrderFile.mockResolvedValue({ filename: "note.jpg", text: "10 [UNCLEAR] olives", method: "ocr" });
  render(<MemoryRouter><NewOrderPage /></MemoryRouter>);
  await screen.findByRole("option", { name: "C7 — Cafe" });
  fireEvent.change(screen.getByLabelText("Customer"), { target: { value: "7" } });
  fireEvent.change(screen.getByLabelText("Customer order file"), {
    target: { files: [new File(["photo"], "note.jpg", { type: "image/jpeg" })] },
  });
  await screen.findByText(/OCR could not read part/);
  expect(screen.getByRole("button", { name: "Parse & Match →" })).toBeDisabled();
});
