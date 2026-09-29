import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { createOrder, previewOrderFile, type OrderFilePreview } from "../api/orders";
import { getCustomers } from "../api/masterData";
import { useCompany } from "../components/AppShell";
import { Alert, Spinner } from "../components/ui";
import type { Customer } from "../types";

export function NewOrderPage() {
  const { companies, companyId, setCompanyId } = useCompany();
  const [customers, setCustomers] = useState<Customer[]>([]);
  const [loadedCompanyId, setLoadedCompanyId] = useState<number | null>(null);
  const [customerId, setCustomerId] = useState("");
  const [customerSearch, setCustomerSearch] = useState("");
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [filePreview, setFilePreview] = useState<OrderFilePreview | null>(null);
  const [error, setError] = useState("");
  const requestKey = useRef(crypto.randomUUID());
  const uploadSequence = useRef(0);
  const navigate = useNavigate();
  useEffect(() => {
    let active = true;
    setLoadedCompanyId(null);
    setCustomers([]);
    setCustomerId("");
    if (companyId) {
      getCustomers(companyId, customerSearch)
        .then((items) => {
          if (!active) return;
          setCustomers(items);
          setLoadedCompanyId(companyId);
        })
        .catch((e) => {
          if (active) setError(e.message);
        });
    }
    return () => {
      active = false;
    };
  }, [companyId, customerSearch]);
  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (
      busy ||
      !companyId ||
      loadedCompanyId !== companyId ||
      !customers.some((c) => String(c.id) === customerId) ||
      !text.trim() || text.toUpperCase().includes("[UNCLEAR]")
    )
      return;
    setBusy(true);
    setError("");
    try {
      const order = await createOrder(
        { company_id: companyId, customer_id: Number(customerId), text },
        requestKey.current,
      );
      navigate(`/orders/${order.id}`);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not create order");
    } finally {
      setBusy(false);
    }
  };
  const resetKey = () => {
    requestKey.current = crypto.randomUUID();
  };
  const uploadFile = async (file: File | undefined) => {
    if (!file) return;
    const sequence = ++uploadSequence.current;
    setUploading(true);
    setError("");
    try {
      const preview = await previewOrderFile(file);
      if (sequence !== uploadSequence.current) return;
      setText(preview.text);
      setFilePreview(preview);
      resetKey();
    } catch (e) {
      if (sequence === uploadSequence.current)
        setError(e instanceof Error ? e.message : "Could not read order file");
    } finally {
      if (sequence === uploadSequence.current) setUploading(false);
    }
  };
  return (
    <>
      <div className="page-head">
        <div>
          <div className="eyebrow">INTAKE / NEW</div>
          <h1>New order</h1>
          <p>
            Paste an order or upload a customer file. Check the extracted text,
            then create a review draft.
          </p>
        </div>
      </div>
      <div className="two-column form-layout">
        <section className="panel padded">
          <h2>Order details</h2>
          <Alert message={error} />
          <form onSubmit={submit} className="stack-form">
            <label>
              Company
              <select
                value={companyId ?? ""}
                onChange={(e) => {
                  setCompanyId(Number(e.target.value));
                  resetKey();
                }}
                required
              >
                <option value="">Select company</option>
                {companies.map((c) => (
                  <option key={c.id} value={c.id}>
                    {c.name}
                  </option>
                ))}
              </select>
            </label>
            {!companies.length && (
              <p>Create a company on the Dashboard before entering an order.</p>
            )}
            <label>
              Find customer
              <input
                value={customerSearch}
                onChange={(e) => setCustomerSearch(e.target.value)}
                placeholder="Search by code or name"
              />
            </label>
            <label>
              Customer
              <select
                value={customerId}
                onChange={(e) => {
                  setCustomerId(e.target.value);
                  resetKey();
                }}
                required
              >
                <option value="">Select customer</option>
                {customers.map((c) => (
                  <option key={c.id} value={c.id}>
                    {c.customer_code} — {c.customer_name}
                  </option>
                ))}
              </select>
            </label>
            <label>
              Customer order file
              <input
                type="file"
                accept=".txt,.csv,.xlsx,.docx,.pdf,.png,.jpg,.jpeg,.webp"
                disabled={uploading || busy}
                onChange={(e) => {
                  void uploadFile(e.target.files?.[0]);
                  e.target.value = "";
                }}
              />
            </label>
            <p className="muted">
              TXT, CSV, Excel (.xlsx), Word (.docx), PDF, JPG, PNG or WebP, up to 10 MB.
              Photos, handwriting and scanned PDFs need a configured Gemini, OpenAI, Claude or Vertex provider in Settings.
            </p>
            {uploading && <p role="status"><Spinner /> Reading file…</p>}
            {filePreview && (
              <p role="status">
                Extracted from <strong>{filePreview.filename}</strong> ({filePreview.method}).
                Check quantities and products against the file before creating the order.
              </p>
            )}
            {text.toUpperCase().includes("[UNCLEAR]") && (
              <p role="alert">OCR could not read part of the file. Correct each [UNCLEAR] from the original before continuing.</p>
            )}
            <label>
              Customer order text
              <textarea
                value={text}
                onChange={(e) => {
                  uploadSequence.current += 1;
                  setUploading(false);
                  setText(e.target.value);
                  if (filePreview) setFilePreview(null);
                  resetKey();
                }}
                rows={12}
                placeholder={"10 κοκκινα\n5 σαλαμια\n3 κουτες γαλοπουλα"}
                required
              />
            </label>
            <button
              className="button primary"
              disabled={
                busy || uploading ||
                !companyId ||
                loadedCompanyId !== companyId ||
                !customers.some((c) => String(c.id) === customerId) ||
                !text.trim() || text.toUpperCase().includes("[UNCLEAR]")
              }
            >
              {busy ? (
                <>
                  <Spinner /> Parsing & matching…
                </>
              ) : (
                "Parse & Match →"
              )}
            </button>
          </form>
        </section>
        <aside className="panel padded help-panel">
          <div className="eyebrow">HOW IT WORKS</div>
          <h2>From customer input to a reviewable order</h2>
          <ol className="steps">
            <li>
              <strong>Paste text or upload a file</strong>
              <span>Review and edit extracted text before parsing. The file itself is not saved.</span>
            </li>
            <li>
              <strong>Review the matches</strong>
              <span>Confidence, reasons and alternatives stay visible.</span>
            </li>
            <li>
              <strong>Approve and export</strong>
              <span>Final values are locked at approval.</span>
            </li>
          </ol>
        </aside>
      </div>
    </>
  );
}
