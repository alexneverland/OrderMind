import { beforeEach, expect, it, vi } from "vitest";
import {
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { ProfilesPage } from "./ProfilesPage";

const mock = vi.hoisted(() => ({
  getProfiles: vi.fn(),
  getSourceFields: vi.fn(),
  createProfile: vi.fn(),
  updateProfile: vi.fn(),
  deleteProfile: vi.fn(),
}));
vi.mock("../components/AppShell", () => ({
  useCompany: () => ({ companyId: 3 }),
}));
vi.mock("../api/exportProfiles", () => mock);

beforeEach(() => {
  vi.clearAllMocks();
  mock.getProfiles.mockResolvedValue([]);
  mock.getSourceFields.mockResolvedValue({ "line.sku": "Final approved SKU" });
  mock.createProfile.mockResolvedValue({ id: 10 });
});

it("creates a profile using the backend source field registry", async () => {
  render(<ProfilesPage />);
  fireEvent.click(screen.getByRole("button", { name: /Create profile/ }));
  const dialog = await screen.findByRole("dialog", {
    name: "Create export profile",
  });
  fireEvent.change(within(dialog).getByRole("textbox", { name: "Name" }), {
    target: { value: "SoftOne" },
  });
  fireEvent.change(
    within(dialog).getByRole("textbox", { name: "Output column" }),
    {
      target: { value: "ITEM" },
    },
  );
  await within(dialog).findByRole("option", { name: /line.sku/ });
  fireEvent.change(
    within(dialog).getByRole("combobox", { name: "Source field" }),
    {
      target: { value: "line.sku" },
    },
  );
  fireEvent.click(within(dialog).getByRole("button", { name: "Save profile" }));
  await waitFor(() =>
    expect(mock.createProfile).toHaveBeenCalledWith(
      expect.objectContaining({
        company_id: 3,
        name: "SoftOne",
        mappings: [
          expect.objectContaining({
            column_order: 1,
            output_column_name: "ITEM",
            source_field: "line.sku",
          }),
        ],
      }),
    ),
  );
});
