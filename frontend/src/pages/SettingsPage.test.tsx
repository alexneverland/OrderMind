import { beforeEach, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { SettingsPage } from "./SettingsPage";

const mock = vi.hoisted(() => ({
  getAISettings: vi.fn(),
  saveAISettings: vi.fn(),
}));
vi.mock("../api/runtimeSettings", () => mock);
vi.mock("../components/AppShell", () => ({
  useCompany: () => ({ companies: [] }),
}));

beforeEach(() => {
  vi.clearAllMocks();
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
