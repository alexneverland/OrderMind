import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { getOrders } from "../api/orders";
import { useAsync } from "../hooks/useAsync";
import { useCompany } from "../components/AppShell";
import {
  Alert,
  Badge,
  dateTime,
  Empty,
  percent,
  Spinner,
} from "../components/ui";

const statuses = [
  ["", "All"],
  ["pending_review", "Pending review"],
  ["approved", "Approved"],
  ["exported", "Exported"],
  ["cancelled", "Cancelled"],
];
export function OrdersPage() {
  const { companyId } = useCompany();
  const [status, setStatus] = useState("");
  const [query, setQuery] = useState("");
  const [search, setSearch] = useState("");
  const [page, setPage] = useState(0);
  useEffect(() => setPage(0), [companyId]);
  const { data, error, loading } = useAsync(
    () =>
      getOrders({
        companyId: companyId || undefined,
        status,
        search,
        limit: 50,
        offset: page * 50,
      }),
    [companyId, status, search, page],
  );
  return (
    <>
      <div className="page-head">
        <div>
          <div className="eyebrow">INTAKE / ORDERS</div>
          <h1>Orders inbox</h1>
          <p>Review incoming orders and keep every decision moving.</p>
        </div>
        <Link className="button primary" to="/orders/new">
          + New order
        </Link>
      </div>
      <section className="panel">
        <div className="toolbar">
          <div className="tabs" role="group" aria-label="Order status">
            {statuses.map(([value, text]) => (
              <button
                key={value}
                className={status === value ? "selected" : ""}
                onClick={() => {
                  setStatus(value);
                  setPage(0);
                }}
              >
                {text}
              </button>
            ))}
          </div>
          <form
            className="search-form"
            onSubmit={(e) => {
              e.preventDefault();
              setSearch(query);
              setPage(0);
            }}
          >
            <input
              aria-label="Search orders"
              placeholder="Order no. or customer"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
            />
            <button className="button" type="submit">
              Search
            </button>
          </form>
        </div>
        <Alert message={error} />
        {loading ? (
          <div className="center">
            <Spinner />
          </div>
        ) : !data?.length ? (
          <Empty>
            No orders found. Create an order or adjust your filters.
          </Empty>
        ) : (
          <div className="table-scroll">
            <table>
              <thead>
                <tr>
                  <th>Order</th>
                  <th>Customer</th>
                  <th>Created</th>
                  <th>Status</th>
                  <th>Lines</th>
                  <th>Confidence</th>
                  <th>Last export</th>
                  <th></th>
                </tr>
              </thead>
              <tbody>
                {data.map((o) => (
                  <tr key={o.id}>
                    <td>
                      <strong>{o.order_number}</strong>
                    </td>
                    <td>
                      {o.customer?.customer_code} · {o.customer?.customer_name}
                    </td>
                    <td>{dateTime(o.created_at)}</td>
                    <td>
                      <Badge status={o.status} />
                    </td>
                    <td>{o.line_count}</td>
                    <td>{percent(o.overall_confidence)}</td>
                    <td>{dateTime(o.exported_at)}</td>
                    <td>
                      <Link to={`/orders/${o.id}`}>Open →</Link>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        {!loading && (
          <div className="pagination">
            <span>Page {page + 1}</span>
            <button
              className="button"
              disabled={page === 0}
              onClick={() => setPage((p) => p - 1)}
            >
              Previous
            </button>
            <button
              className="button"
              disabled={(data?.length || 0) < 50}
              onClick={() => setPage((p) => p + 1)}
            >
              Next
            </button>
          </div>
        )}
      </section>
    </>
  );
}
