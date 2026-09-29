import { useState } from "react";
import { createCustomer, createProduct } from "../api/masterData";
import { useCompany } from "./AppShell";
import { Alert, Spinner } from "./ui";

export function CompanySetup() {
  const { addCompany } = useCompany();
  const [name, setName] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      await addCompany(name.trim());
      setName("");
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };
  return (
    <section className="panel padded setup-panel">
      <h2>Create company</h2>
      <p>Each company has its own customers, products and orders.</p>
      <Alert message={error} />
      <form className="setup-form" onSubmit={(e) => void submit(e)}>
        <label>
          Company name
          <input
            value={name}
            onChange={(e) => setName(e.target.value)}
            required
          />
        </label>
        <button className="button primary" disabled={busy || !name.trim()}>
          {busy ? <Spinner /> : "Create company"}
        </button>
      </form>
    </section>
  );
}

export function CustomerSetup({
  companyId,
  onCreated,
}: {
  companyId: number;
  onCreated: () => Promise<void>;
}) {
  const [code, setCode] = useState("");
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [phone, setPhone] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      await createCustomer({
        company_id: companyId,
        customer_code: code,
        customer_name: name,
        email,
        phone,
      });
      setCode("");
      setName("");
      setEmail("");
      setPhone("");
      await onCreated();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };
  return (
    <section className="panel padded setup-panel">
      <h2>Add customer</h2>
      <Alert message={error} />
      <form className="setup-form" onSubmit={(e) => void submit(e)}>
        <label>
          Customer code
          <input
            value={code}
            onChange={(e) => setCode(e.target.value)}
            required
          />
        </label>
        <label>
          Name
          <input
            value={name}
            onChange={(e) => setName(e.target.value)}
            required
          />
        </label>
        <label>
          Email
          <input
            type="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
          />
        </label>
        <label>
          Phone
          <input value={phone} onChange={(e) => setPhone(e.target.value)} />
        </label>
        <button className="button primary" disabled={busy}>
          {busy ? <Spinner /> : "Add customer"}
        </button>
      </form>
    </section>
  );
}

export function ProductSetup({
  companyId,
  onCreated,
}: {
  companyId: number;
  onCreated: () => Promise<void>;
}) {
  const [sku, setSku] = useState("");
  const [description, setDescription] = useState("");
  const [barcode, setBarcode] = useState("");
  const [unit, setUnit] = useState("piece");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      await createProduct({
        company_id: companyId,
        sku,
        description,
        barcode,
        unit,
      });
      setSku("");
      setDescription("");
      setBarcode("");
      await onCreated();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };
  return (
    <section className="panel padded setup-panel">
      <h2>Add product</h2>
      <Alert message={error} />
      <form className="setup-form" onSubmit={(e) => void submit(e)}>
        <label>
          SKU
          <input
            value={sku}
            onChange={(e) => setSku(e.target.value)}
            required
          />
        </label>
        <label>
          Description
          <input
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            required
          />
        </label>
        <label>
          Barcode
          <input value={barcode} onChange={(e) => setBarcode(e.target.value)} />
        </label>
        <label>
          Unit
          <select value={unit} onChange={(e) => setUnit(e.target.value)}>
            <option value="piece">piece</option>
            <option value="case">case</option>
            <option value="kg">kg</option>
            <option value="pallet">pallet</option>
          </select>
        </label>
        <button className="button primary" disabled={busy}>
          {busy ? <Spinner /> : "Add product"}
        </button>
      </form>
    </section>
  );
}
