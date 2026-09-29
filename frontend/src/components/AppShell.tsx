import { NavLink, Outlet } from "react-router-dom";
import { createContext, useContext, useEffect, useState } from "react";
import { createCompany, getCompanies } from "../api/masterData";
import type { Company } from "../types";
import { Alert } from "./ui";

type CompanyContextValue = {
  companies: Company[];
  companiesLoading: boolean;
  companyId: number | null;
  setCompanyId: (id: number) => void;
  addCompany: (name: string) => Promise<void>;
};
const CompanyContext = createContext<CompanyContextValue>({
  companies: [],
  companiesLoading: true,
  companyId: null,
  setCompanyId: () => {},
  addCompany: async () => {},
});
export const useCompany = () => useContext(CompanyContext);

const links = [
  ["/", "Dashboard"],
  ["/orders", "Orders"],
  ["/orders/new", "New order"],
  ["/customers", "Customers"],
  ["/products", "Products"],
  ["/export-profiles", "Export profiles"],
  ["/settings", "Settings"],
];
export function AppShell() {
  const [companies, setCompanies] = useState<Company[]>([]);
  const [companiesLoading, setCompaniesLoading] = useState(true);
  const [companyId, setCompanyId] = useState<number | null>(null);
  const [error, setError] = useState("");
  useEffect(() => {
    getCompanies()
      .then((items) => {
        setCompanies(items);
        const saved = Number(localStorage.getItem("ordermind-company"));
        setCompanyId(
          items.some((x) => x.id === saved) ? saved : items[0]?.id || null,
        );
      })
      .catch((e) => setError(e.message))
      .finally(() => setCompaniesLoading(false));
  }, []);
  const selectCompany = (id: number) => {
    setCompanyId(id);
    localStorage.setItem("ordermind-company", String(id));
  };
  const addCompany = async (name: string) => {
    const company = await createCompany(name);
    setCompanies((items) => [...items, company]);
    selectCompany(company.id);
  };
  return (
    <CompanyContext.Provider
      value={{
        companies,
        companiesLoading,
        companyId,
        setCompanyId: selectCompany,
        addCompany,
      }}
    >
      <div className="app-shell">
        <aside className="sidebar">
          <div className="brand">
            <span className="brand-mark">OM</span>
            <span>
              <strong>OrderMind</strong>
              <small>Operator workspace</small>
            </span>
          </div>
          <nav aria-label="Main navigation">
            {links.map(([path, name]) => (
              <NavLink
                key={path}
                to={path}
                end={path === "/" || path === "/orders"}
                className={({ isActive }) =>
                  `nav-link ${isActive ? "active" : ""}`
                }
              >
                {name}
              </NavLink>
            ))}
          </nav>
          <div className="sidebar-foot">B2B order intelligence</div>
        </aside>
        <div className="main-area">
          <header className="topbar">
            <div className="mobile-brand">OrderMind</div>
            <span className="topbar-label">Workspace</span>
            <label className="company-switcher">
              Company{" "}
              <select
                value={companyId ?? ""}
                onChange={(e) => selectCompany(Number(e.target.value))}
                aria-label="Current company"
              >
                <option value="" disabled>
                  Select company
                </option>
                {companies.map((c) => (
                  <option value={c.id} key={c.id}>
                    {c.name}
                  </option>
                ))}
              </select>
            </label>
          </header>
          <main className="content">
            <Alert message={error} />
            <Outlet />
          </main>
        </div>
      </div>
    </CompanyContext.Provider>
  );
}
