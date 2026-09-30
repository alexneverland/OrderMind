import { useState } from "react";
import { Link } from "react-router-dom";
import { getCustomers, getProducts, setProductWeight, setPackagingWeight } from "../api/masterData";
import { getOrders, getOrderStats } from "../api/orders";
import { useCompany } from "../components/AppShell";
import { ExcelImportPanel } from "../components/ExcelImportPanel";
import { useAsync } from "../hooks/useAsync";
import { Alert, Badge, dateTime, Empty, Spinner } from "../components/ui";
import {
  CompanySetup,
  CustomerSetup,
  ProductSetup,
} from "../components/SetupForms";

export function CustomersPage() {
  const { companyId, companiesLoading } = useCompany();
  const [query, setQuery] = useState("");
  const [search, setSearch] = useState("");
  const { data, error, loading, refresh } = useAsync(
    () => (companyId ? getCustomers(companyId, search) : Promise.resolve([])),
    [companyId, search],
  );
  return (
    <>
      <div className="page-head">
        <div>
          <div className="eyebrow">MASTER DATA</div>
          <h1>Customers</h1>
          <p>Customers in the selected company.</p>
        </div>
        <a className="button primary" href="#customer-import">
          Import Excel
        </a>
      </div>
      <section className="panel">
        <form
          className="toolbar search-form"
          onSubmit={(e) => {
            e.preventDefault();
            setSearch(query);
          }}
        >
          <input
            aria-label="Search customers"
            placeholder="Search code or name"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
          />
          <button className="button">Search</button>
        </form>
        <Alert message={error} />
        {loading ? (
          <div className="center">
            <Spinner />
          </div>
        ) : !data?.length ? (
          <Empty>No customers found.</Empty>
        ) : (
          <div className="table-scroll">
            <table>
              <thead>
                <tr>
                  <th>Code</th>
                  <th>Name</th>
                  <th>Email</th>
                  <th>Phone</th>
                </tr>
              </thead>
              <tbody>
                {data.map((c) => (
                  <tr key={c.id}>
                    <td>
                      <strong>{c.customer_code}</strong>
                    </td>
                    <td>{c.customer_name}</td>
                    <td>{c.email || "—"}</td>
                    <td>{c.phone || "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
      {!companyId && !companiesLoading && (
        <section className="setup-guide">
          <p>Create your first company to import customers from Excel.</p>
          <CompanySetup />
        </section>
      )}
      <ExcelImportPanel
        id="customer-import"
        key={`customers-${companyId ?? "none"}`}
        entity="customers"
        companyId={companyId}
        onImported={refresh}
      />
      {companyId && <CustomerSetup companyId={companyId} onCreated={refresh} />}
    </>
  );
}
export function ProductsPage() {
  const { companyId, companiesLoading } = useCompany();
  const [query, setQuery] = useState("");
  const [search, setSearch] = useState("");
  const [weightError, setWeightError] = useState("");
  const editWeight = async (productId: number, current: number | null) => {
    if (!companyId) return;
    const input = window.prompt("Gross kg per piece (leave empty to clear)", current == null ? "" : String(current));
    if (input === null) return;
    const value = input.trim() ? Number(input) : null;
    if (value !== null && (!Number.isFinite(value) || value < 0.000001 || value > 1_000_000)) { setWeightError("Enter gross kg per piece between 0.000001 and 1,000,000."); return; }
    try { setWeightError(""); await setProductWeight(companyId, productId, value); await refresh(); }
    catch (cause) { setWeightError((cause as Error).message); }
  };
  const editCaseWeight = async (packagingId: number, current: number | null) => {
    if (!companyId) return;
    const input = window.prompt("Gross kg per case (leave empty to clear)", current == null ? "" : String(current));
    if (input === null) return;
    const value = input.trim() ? Number(input) : null;
    if (value !== null && (!Number.isFinite(value) || value < 0.000001 || value > 1_000_000)) { setWeightError("Enter gross kg per case between 0.000001 and 1,000,000."); return; }
    try { setWeightError(""); await setPackagingWeight(companyId, packagingId, value); await refresh(); }
    catch (cause) { setWeightError((cause as Error).message); }
  };
  const { data, error, loading, refresh } = useAsync(
    () => (companyId ? getProducts(companyId, search) : Promise.resolve([])),
    [companyId, search],
  );
  return (
    <>
      <div className="page-head">
        <div>
          <div className="eyebrow">MASTER DATA</div>
          <h1>Products</h1>
          <p>Search the active product catalog. Pallet weight uses trusted gross kilograms per piece.</p>
        </div>
        <div className="page-actions">
          <a className="button primary" href="#product-import">
            Import products
          </a>
          <a className="button" href="#packaging-import">
            Import packaging
          </a>
        </div>
      </div>
      <section className="panel">
        <form
          className="toolbar search-form"
          onSubmit={(e) => {
            e.preventDefault();
            setSearch(query);
          }}
        >
          <input
            aria-label="Search products"
            placeholder="SKU, description or barcode"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
          />
          <button className="button">Search</button>
        </form>
        <Alert message={error || weightError} />
        {loading ? (
          <div className="center">
            <Spinner />
          </div>
        ) : !data?.length ? (
          <Empty>No products found.</Empty>
        ) : (
          <div className="table-scroll">
            <table>
              <thead>
                <tr>
                  <th>SKU</th>
                  <th>Description</th>
                  <th>Barcode</th>
                  <th>Unit</th>
                  <th>Gross kg / piece</th>
                  <th>Active</th>
                  <th>Packaging</th>
                </tr>
              </thead>
              <tbody>
                {data.map((p) => (
                  <tr key={p.id}>
                    <td>
                      <strong>{p.sku}</strong>
                    </td>
                    <td>{p.description}</td>
                    <td>{p.barcode || "—"}</td>
                    <td>{p.unit}</td>
                    <td><button className="text-button" onClick={() => void editWeight(p.id, p.kg_per_piece)}>
                      {p.kg_per_piece ?? "Set weight"}
                    </button></td>
                    <td>{p.active ? "Yes" : "No"}</td>
                    <td>{p.packagings?.length ? <details><summary>{p.packagings.length} packages</summary>
                      {p.packagings.map((packaging) => <div key={packaging.id}>
                        {packaging.package_code || packaging.package_type} · {packaging.pieces_per_case} pieces/case ·
                        <button className="text-button" onClick={() => void editCaseWeight(packaging.id, packaging.kg_per_case)}>
                          {packaging.kg_per_case ?? "Set gross kg/case"}
                        </button>
                      </div>)}
                    </details> : "0"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
      {!companyId && !companiesLoading && (
        <section className="setup-guide">
          <p>Create your first company to import products from Excel.</p>
          <CompanySetup />
        </section>
      )}
      <ExcelImportPanel
        id="product-import"
        key={`products-${companyId ?? "none"}`}
        entity="products"
        companyId={companyId}
        onImported={refresh}
      />
      {companyId && <ProductSetup companyId={companyId} onCreated={refresh} />}
      <ExcelImportPanel
        key={`packaging-${companyId ?? "none"}`}
        id="packaging-import"
        entity="packaging"
        companyId={companyId}
        onImported={refresh}
      />
    </>
  );
}
export function DashboardPage() {
  const { companyId, companies, companiesLoading } = useCompany();
  const { data, error, loading } = useAsync(
    () => getOrders({ companyId: companyId || undefined }),
    [companyId],
  );
  const { data: stats, error: statsError } = useAsync(
    () => getOrderStats(companyId || undefined),
    [companyId],
  );
  return (
    <>
      <div className="page-head">
        <div>
          <div className="eyebrow">OVERVIEW</div>
          <h1>Good to see you.</h1>
          <p>Here is what needs attention in your order workspace.</p>
        </div>
        <Link className="button primary" to="/orders/new">
          + New order
        </Link>
      </div>
      <Alert message={error || statsError} />
      {!companiesLoading && !companies.length && <CompanySetup />}
      <div className="dashboard-stats">
        <div className="panel">
          <span>Pending review</span>
          <strong>{stats?.pending_review ?? "—"}</strong>
        </div>
        <div className="panel">
          <span>Approved today</span>
          <strong>{stats?.approved_today ?? "—"}</strong>
        </div>
        <div className="panel">
          <span>Exported today</span>
          <strong>{stats?.exported_today ?? "—"}</strong>
        </div>
        <div className="panel">
          <span>Needs attention</span>
          <strong>{stats?.needs_attention ?? "—"}</strong>
        </div>
      </div>
      <section className="panel padded">
        <div className="section-heading">
          <h2>Recent orders</h2>
          <Link to="/orders">View all →</Link>
        </div>
        {loading ? (
          <Spinner />
        ) : !data?.length ? (
          <Empty>
            No orders yet. <Link to="/orders/new">Create your first order</Link>
            .
          </Empty>
        ) : (
          <div className="recent-list">
            {data.slice(0, 6).map((o) => (
              <Link to={`/orders/${o.id}`} key={o.id}>
                <strong>{o.order_number}</strong>
                <span>{o.customer?.customer_name}</span>
                <Badge status={o.status} />
                <small>{dateTime(o.created_at)}</small>
              </Link>
            ))}
          </div>
        )}
      </section>
    </>
  );
}
