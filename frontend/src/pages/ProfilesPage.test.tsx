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

it("creates the fixed four-column order sheet profile", async () => {
  render(<ProfilesPage />);
  fireEvent.click(await screen.findByRole("button", { name: /4-column order sheet/ }));
  await waitFor(() => expect(mock.createProfile).toHaveBeenCalledWith(
    expect.objectContaining({ company_id: 3, format: "order_sheet", include_header: false, mappings: [] }),
  ));
});

it("saves explicit order sheet marker and conversion policy", async () => {
  render(<ProfilesPage />);
  fireEvent.click(screen.getByRole("button", { name: /Create profile/ }));
  const dialog = await screen.findByRole("dialog", { name: "Create export profile" });
  fireEvent.change(within(dialog).getByRole("textbox", { name: "Name" }), { target: { value: "Company A sheet" } });
  fireEvent.change(within(dialog).getByRole("combobox", { name: "Format" }), { target: { value: "order_sheet" } });
  expect(within(dialog).getByRole("combobox", { name: "Output quantity unit" })).toHaveValue("source");
  expect(within(dialog).getByLabelText("Separate bonus row")).not.toBeChecked();
  fireEvent.click(within(dialog).getByLabelText("Separate bonus row"));
  fireEvent.change(within(dialog).getByRole("textbox", { name: "Bonus marker" }), { target: { value: "FREE" } });
  fireEvent.change(within(dialog).getByRole("combobox", { name: "Output quantity unit" }), { target: { value: "piece" } });
  fireEvent.click(within(dialog).getByRole("button", { name: "Save profile" }));
  await waitFor(() => expect(mock.createProfile).toHaveBeenCalledWith(expect.objectContaining({
    company_id: 3, bonus_separate_row: true, bonus_marker: "FREE", quantity_output_unit: "piece",
    convert_case_using_pieces_per_case: true, mappings: [],
  })));
});

it("edits a company profile without reverting its existing rules", async () => {
  mock.getProfiles.mockResolvedValue([{
    id: 19, company_id: 3, name: "Legacy sheet", format: "order_sheet",
    delimiter: ",", encoding: "utf-8-sig", include_header: false,
    bonus_separate_row: true, bonus_marker: "Α", quantity_output_unit: "piece",
    convert_case_using_pieces_per_case: true, field_mappings: [],
  }]);
  mock.updateProfile.mockResolvedValue({ id: 19 });
  render(<ProfilesPage />);
  fireEvent.click(await screen.findByRole("button", { name: "Edit" }));
  const dialog = screen.getByRole("dialog", { name: "Edit export profile" });
  expect(within(dialog).getByRole("combobox", { name: "Format" })).toBeDisabled();
  expect(within(dialog).getByRole("textbox", { name: "Bonus marker" })).toHaveValue("Α");
  expect(within(dialog).getByRole("combobox", { name: "Output quantity unit" })).toHaveValue("piece");
  fireEvent.click(within(dialog).getByRole("button", { name: "Save profile" }));
  await waitFor(() => expect(mock.updateProfile).toHaveBeenCalledWith(19, expect.objectContaining({
    company_id: 3, bonus_separate_row: true, bonus_marker: "Α", quantity_output_unit: "piece",
    convert_case_using_pieces_per_case: true,
  })));
});
