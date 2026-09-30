import { beforeEach, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { SettingsPage } from "./SettingsPage";

const mock = vi.hoisted(() => ({
  getAISettings: vi.fn(),
  saveAISettings: vi.fn(),
  getBusinessSettings: vi.fn(),
  saveBusinessSettings: vi.fn(),
  getCompanyRules: vi.fn(),
  analyzeRules: vi.fn(),
  applyRules: vi.fn(),
  createRule: vi.fn(),
  updateRule: vi.fn(),
  disableRule: vi.fn(),
  getProducts: vi.fn(),
  getCustomers: vi.fn(),
  companyId: 1,
}));
vi.mock("../api/runtimeSettings", () => mock);
vi.mock("../api/businessSettings", () => mock);
vi.mock("../api/rules", () => mock);
vi.mock("../api/masterData", () => mock);
vi.mock("../components/AppShell", () => ({
  useCompany: () => ({ companyId: mock.companyId, companies: [
    { id: 1, name: "Company A" }, { id: 2, name: "Company B" },
  ] }),
}));

beforeEach(() => {
  vi.clearAllMocks();
  mock.companyId = 1;
  mock.getBusinessSettings.mockImplementation(async (id: number) => ({
    company_id: id, bonus_enabled: id === 1,
    bonus_expression_mode: id === 1 ? "paid_plus_bonus" : "disabled",
    unitless_order_behavior: "require_review",
    allow_packaging_conversion: false, learn_unit_preferences: false,
  }));
  mock.saveBusinessSettings.mockImplementation(async (value) => value);
  mock.getCompanyRules.mockResolvedValue([]);
  mock.getProducts.mockResolvedValue([{ id: 10, company_id: 1, sku: "SKU-10", description: "Product" }]);
  mock.getCustomers.mockResolvedValue([{ id: 20, company_id: 1, customer_code: "BUYER", customer_name: "Buyer" }]);
  mock.createRule.mockResolvedValue({ id: 5 });
  mock.updateRule.mockResolvedValue({ id: 5 });
  mock.disableRule.mockResolvedValue(undefined);
  mock.getAISettings.mockResolvedValue({
    provider: "mock",
    model: "mock-model",
    gemini_key_configured: false,
    openai_key_configured: false,
    anthropic_key_configured: false,
    google_cloud_project: null,
    google_cloud_location: "us-central1",
  });
  mock.saveAISettings.mockResolvedValue({
    provider: "gemini",
    model: "gemini-test",
    gemini_key_configured: true,
    openai_key_configured: false,
    anthropic_key_configured: false,
    google_cloud_project: null,
    google_cloud_location: "us-central1",
  });
});

it("loads neutral rules for another selected company and saves only that company", async () => {
  const view = render(<MemoryRouter><SettingsPage /></MemoryRouter>);
  expect(await screen.findByText("Company A")).toBeInTheDocument();
  expect(await screen.findByRole("option", { name: "10+1 means paid + bonus" })).toBeInTheDocument();
  expect(screen.getByLabelText("Allow customer-stated free quantities")).toBeChecked();

  mock.companyId = 2;
  view.rerender(<MemoryRouter><SettingsPage /></MemoryRouter>);
  expect(await screen.findByText("Company B")).toBeInTheDocument();
  await waitFor(() => expect(mock.getBusinessSettings).toHaveBeenCalledWith(2));
  await waitFor(() => expect(screen.getByLabelText("Allow customer-stated free quantities")).not.toBeChecked());
  expect(screen.getByRole("combobox", { name: "When customer does not specify a unit" })).toHaveValue("require_review");
  fireEvent.click(screen.getByRole("button", { name: "Save company rules" }));
  await waitFor(() => expect(mock.saveBusinessSettings).toHaveBeenCalledWith(
    expect.objectContaining({ company_id: 2, bonus_enabled: false }),
  ));
});

it("offers OpenAI, Claude and Vertex with provider-specific credentials", async () => {
  render(<MemoryRouter><SettingsPage /></MemoryRouter>);
  const select = await screen.findByRole("combobox", { name: "Provider" });
  expect(screen.getByRole("option", { name: "OpenAI" })).toBeInTheDocument();
  expect(screen.getByRole("option", { name: "Claude (Anthropic)" })).toBeInTheDocument();
  expect(screen.getByRole("option", { name: "Vertex AI (Google Cloud)" })).toBeInTheDocument();
  fireEvent.change(select, { target: { value: "openai" } });
  fireEvent.change(screen.getByLabelText(/OpenAI API key/), { target: { value: "test-openai-key" } });
  fireEvent.click(screen.getByRole("button", { name: "Save AI settings" }));
  await waitFor(() => expect(mock.saveAISettings).toHaveBeenCalledWith({
    provider: "openai", model: "gpt-4.1-mini", openai_api_key: "test-openai-key",
  }));
});

it("configures Gemini without displaying a saved key", async () => {
  render(
    <MemoryRouter>
      <SettingsPage />
    </MemoryRouter>,
  );
  fireEvent.change(await screen.findByRole("combobox", { name: "Provider" }), {
    target: { value: "gemini" },
  });
  fireEvent.change(screen.getByRole("textbox", { name: "Model" }), {
    target: { value: "gemini-test" },
  });
  fireEvent.change(screen.getByLabelText(/Gemini API key/), {
    target: { value: "example-test-key" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Save AI settings" }));
  await waitFor(() =>
    expect(mock.saveAISettings).toHaveBeenCalledWith({
      provider: "gemini",
      model: "gemini-test",
      gemini_api_key: "example-test-key",
    }),
  );
  expect(await screen.findByText(/AI settings saved/)).toBeVisible();
  expect(screen.getByLabelText(/Gemini API key/)).toHaveValue("");
});

it("shows a structured proposal and only applies it after the operator confirms", async () => {
  mock.analyzeRules.mockResolvedValue({
    settings_patch: { unitless_order_behavior: "piece" },
    quantity_rules: [{
      configuration: { trigger: { mode: "per_quantity", quantity: 10, unit: "case" }, reward: { quantity: 1, unit: "case" } },
      product_reference: "SKU-10", product_id: 10, product_candidates: [{ id: 10, label: "SKU-10 · Product" }],
      customer_reference: null, customer_id: null, customer_candidates: [],
    }],
    export_patch: null, export_profile_candidates: [],
    unsupported_rules: [{ text: "weather discount", reason: "Not supported" }],
  });
  mock.applyRules.mockResolvedValue({ settings: {
    company_id: 1, bonus_enabled: true, bonus_expression_mode: "paid_plus_bonus",
    unitless_order_behavior: "piece", allow_packaging_conversion: false, learn_unit_preferences: false,
  }, rules: [] });
  render(<MemoryRouter><SettingsPage /></MemoryRouter>);
  fireEvent.change(await screen.findByRole("textbox", { name: "Describe company rules" }), {
    target: { value: "Every 10 cases of SKU-10 gives 1 free case" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Analyze rules" }));
  expect(await screen.findByText(/Every 10 cases → \+1 free case/)).toBeInTheDocument();
  expect(screen.getByText(/Unsupported: weather discount/)).toBeInTheDocument();
  expect(mock.applyRules).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole("button", { name: "Apply rules" }));
  await waitFor(() => expect(mock.applyRules).toHaveBeenCalledWith(1, expect.objectContaining({
    quantity_rules: [expect.objectContaining({ product_id: 10 })],
  })));
  expect(await screen.findByText("Rules applied to this company.")).toBeInTheDocument();
});

it("keeps active promotions editable and manual company settings under Advanced settings", async () => {
  mock.getCompanyRules.mockResolvedValue([{ id: 5, company_id: 1, enabled: true, rule_type: "quantity_bonus",
    product_id: null, customer_id: null,
    configuration: { trigger: { mode: "greater_than", quantity: 30, unit: "piece" }, reward: { quantity: 2, unit: "piece" } },
  }]);
  render(<MemoryRouter><SettingsPage /></MemoryRouter>);
  expect(await screen.findByText(/Promotion · Above 30 pieces/)).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Edit" }));
  expect(screen.getByRole("combobox", { name: "Trigger mode" })).toHaveValue("greater_than");
  fireEvent.click(screen.getByText("Advanced settings"));
  expect(screen.getByLabelText("Allow customer-stated free quantities")).toBeChecked();
  fireEvent.click(screen.getByRole("button", { name: "Disable" }));
  await waitFor(() => expect(mock.disableRule).toHaveBeenCalledWith(1, 5));
});

it("saves a typed manual promotion scoped to the selected company product", async () => {
  render(<MemoryRouter><SettingsPage /></MemoryRouter>);
  fireEvent.click(await screen.findByText("Add promotion manually"));
  fireEvent.change(screen.getByRole("spinbutton", { name: "Trigger quantity" }), { target: { value: "5" } });
  fireEvent.change(screen.getByRole("combobox", { name: "Product scope" }), { target: { value: "10" } });
  fireEvent.click(screen.getByRole("button", { name: "Save promotion" }));
  await waitFor(() => expect(mock.createRule).toHaveBeenCalledWith(1, expect.objectContaining({
    rule_type: "quantity_bonus", product_id: 10,
    configuration: expect.objectContaining({ trigger: expect.objectContaining({ mode: "per_quantity", quantity: 5, unit: "case" }) }),
  })));
});
