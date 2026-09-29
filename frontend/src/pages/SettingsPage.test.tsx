import { beforeEach, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { SettingsPage } from "./SettingsPage";

const mock = vi.hoisted(() => ({
  getAISettings: vi.fn(),
  saveAISettings: vi.fn(),
  getBusinessSettings: vi.fn(),
  saveBusinessSettings: vi.fn(),
  companyId: 1,
}));
vi.mock("../api/runtimeSettings", () => mock);
vi.mock("../api/businessSettings", () => mock);
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
  expect(screen.getByLabelText("Enable paid and bonus quantities")).toBeChecked();

  mock.companyId = 2;
  view.rerender(<MemoryRouter><SettingsPage /></MemoryRouter>);
  expect(await screen.findByText("Company B")).toBeInTheDocument();
  await waitFor(() => expect(mock.getBusinessSettings).toHaveBeenCalledWith(2));
  await waitFor(() => expect(screen.getByLabelText("Enable paid and bonus quantities")).not.toBeChecked());
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
