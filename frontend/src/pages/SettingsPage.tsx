import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import {
  getAISettings,
  saveAISettings,
  type AISettings,
} from "../api/runtimeSettings";
import { useCompany } from "../components/AppShell";
import { getBusinessSettings, saveBusinessSettings, type BusinessSettings } from "../api/businessSettings";
import { Alert, Spinner } from "../components/ui";
import { CompanyRulesWorkspace } from "../components/CompanyRulesWorkspace";

export function SettingsPage() {
  const { companies, companyId } = useCompany();
  const [business, setBusiness] = useState<BusinessSettings | null>(null);
  const [businessError, setBusinessError] = useState("");
  const [businessBusy, setBusinessBusy] = useState(false);
  const [businessSaved, setBusinessSaved] = useState(false);
  const [advancedOpen, setAdvancedOpen] = useState(false);
  useEffect(() => {
    let active = true;
    setBusiness(null);
    setBusinessError("");
    setBusinessSaved(false);
    if (companyId) getBusinessSettings(companyId)
      .then((value) => { if (active) setBusiness(value); })
      .catch((e) => { if (active) setBusinessError((e as Error).message); });
    return () => { active = false; };
  }, [companyId]);
  const saveBusiness = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!business || !companyId || business.company_id !== companyId) return;
    setBusinessBusy(true);
    setBusinessError("");
    setBusinessSaved(false);
    try {
      setBusiness(await saveBusinessSettings(business));
      setBusinessSaved(true);
    } catch (e) {
      setBusinessError((e as Error).message);
    } finally {
      setBusinessBusy(false);
    }
  };
  const [current, setCurrent] = useState<AISettings | null>(null);
  const [provider, setProvider] = useState<AISettings["provider"]>("mock");
  const [model, setModel] = useState("mock-model");
  const [key, setKey] = useState("");
  const [project, setProject] = useState("");
  const [location, setLocation] = useState("us-central1");
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    getAISettings()
      .then((value) => {
        setCurrent(value);
        setProvider(value.provider);
        setModel(value.model);
        setProject(value.google_cloud_project || "");
        setLocation(value.google_cloud_location || "us-central1");
      })
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }, []);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (busy) return;
    setBusy(true);
    setError("");
    setSaved(false);
    try {
      const result = await saveAISettings({
        provider,
        model: model.trim(),
        ...(key.trim() ? { [`${provider === "anthropic" ? "anthropic" : provider}_api_key`]: key.trim() } : {}),
        ...(provider === "vertex" ? { google_cloud_project: project.trim(), google_cloud_location: location.trim() } : {}),
      });
      setCurrent(result);
      setKey("");
      setSaved(true);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <>
      <div className="page-head">
        <div>
          <div className="eyebrow">WORKSPACE</div>
          <h1>Settings</h1>
          <p>Configure order extraction for this local OrderMind instance.</p>
        </div>
      </div>
      <Alert message={error} />
      <section className="panel padded settings-panel">
        <h2>AI extraction</h2>
        <p>
          Mock runs without a key. Gemini, OpenAI and Claude use your own API key; Vertex uses Google Cloud Application Default Credentials. Catalog
          matching still uses your company data.
        </p>
        {loading ? (
          <Spinner />
        ) : (
          current && (
            <form className="stack-form" onSubmit={(e) => void submit(e)}>
              <label>
                Provider
                <select
                  value={provider}
                  onChange={(e) => {
                    const next = e.target.value as AISettings["provider"];
                    setProvider(next);
                    setModel(({ mock: "mock-model", gemini: "gemini-3.8-flash", vertex: "gemini-3.8-flash", openai: "gpt-4.1-mini", anthropic: "claude-sonnet-4-6" })[next]);
                    setKey("");
                    setSaved(false);
                  }}
                >
                  <option value="mock">Mock (offline)</option>
                  <option value="gemini">Gemini</option>
                  <option value="openai">OpenAI</option>
                  <option value="anthropic">Claude (Anthropic)</option>
                  <option value="vertex">Vertex AI (Google Cloud)</option>
                </select>
              </label>
              <label>
                Model
                <input
                  value={model}
                  onChange={(e) => {
                    setModel(e.target.value);
                    setSaved(false);
                  }}
                  required
                  maxLength={120}
                />
              </label>
              {provider !== "mock" && provider !== "vertex" && (
                <label>
                  {provider === "anthropic" ? "Claude" : provider === "openai" ? "OpenAI" : "Gemini"} API key
                  <input
                    type="password"
                    autoComplete="off"
                    value={key}
                    onChange={(e) => {
                      setKey(e.target.value);
                      setSaved(false);
                    }}
                    placeholder={
                      current[`${provider}_key_configured`]
                        ? "Key already configured; leave blank to keep it"
                        : "Enter API key"
                    }
                  />
                  <small>
                    {current[`${provider}_key_configured`]
                      ? "A key is configured. Its value is never displayed."
                      : "No key configured yet."}
                  </small>
                </label>
              )}
              {provider === "vertex" && (
                <>
                  <label>Google Cloud project
                    <input value={project} onChange={(e) => setProject(e.target.value)} required maxLength={120} />
                  </label>
                  <label>Google Cloud location
                    <input value={location} onChange={(e) => setLocation(e.target.value)} required maxLength={120} />
                  </label>
                  <small>Vertex requires Application Default Credentials on this computer and access to the selected project.</small>
                </>
              )}
              <button
                className="button primary"
                disabled={
                  busy ||
                  !model.trim() ||
                  (provider !== "mock" && provider !== "vertex" && !current[`${provider}_key_configured`] && !key.trim()) ||
                  (provider === "vertex" && (!project.trim() || !location.trim()))
                }
              >
                {busy ? <Spinner /> : "Save AI settings"}
              </button>
              {saved && (
                <p role="status">
                  AI settings saved and active for new orders.
                </p>
              )}
            </form>
          )
        )}
      </section>
      <section className="panel padded settings-panel">
        <h2>Company business rules</h2>
        <p>These rules apply only to: <strong>{companies.find((c) => c.id === companyId)?.name || "Select a company"}</strong>.</p>
        <Alert message={businessError} />
        {companyId && !business && !businessError && <Spinner />}
        {business && business.company_id === companyId && <CompanyRulesWorkspace
          key={companyId} companyId={companyId} business={business} onBusinessChanged={setBusiness}
          onEditSettings={() => setAdvancedOpen(true)} />}
        {business && business.company_id === companyId && (
          <details className="line-details" open={advancedOpen} onToggle={(event) => setAdvancedOpen(event.currentTarget.open)}><summary>Advanced settings</summary>
          <form className="stack-form" onSubmit={(e) => void saveBusiness(e)}>
            <label className="check-row"><input type="checkbox" checked={business.bonus_enabled}
              onChange={(e) => setBusiness({ ...business, bonus_enabled: e.target.checked,
                bonus_expression_mode: e.target.checked ? "explicit_only" : "disabled" })} /> Allow customer-stated free quantities</label>
            <label>Promotion syntax
              <select value={business.bonus_expression_mode} disabled={!business.bonus_enabled}
                onChange={(e) => setBusiness({ ...business, bonus_expression_mode: e.target.value as BusinessSettings["bonus_expression_mode"] })}>
                <option value="disabled">Disabled</option>
                <option value="explicit_only">Only explicitly free goods</option>
                <option value="paid_plus_bonus">10+1 means paid + bonus</option>
              </select>
            </label>
            <label>When customer does not specify a unit
              <select value={business.unitless_order_behavior}
                onChange={(e) => setBusiness({ ...business, unitless_order_behavior: e.target.value as BusinessSettings["unitless_order_behavior"],
                  learn_unit_preferences: e.target.value === "learned_product_preference" ? true : business.learn_unit_preferences })}>
                <option value="require_review">Require review</option>
                <option value="piece">Piece</option>
                <option value="product_master_unit">Product master unit</option>
                <option value="learned_product_preference">Learned product preference</option>
              </select>
            </label>
            <label className="check-row"><input type="checkbox" checked={business.learn_unit_preferences}
              disabled={business.unitless_order_behavior === "learned_product_preference"}
              onChange={(e) => setBusiness({ ...business, learn_unit_preferences: e.target.checked })} /> Learn unit preferences from operator corrections</label>
            <label className="check-row"><input type="checkbox" checked={business.allow_packaging_conversion}
              onChange={(e) => setBusiness({ ...business, allow_packaging_conversion: e.target.checked })} /> Allow case to piece conversion using packaging ratios</label>
            <button className="button primary" disabled={businessBusy}>{businessBusy ? <Spinner /> : "Save company rules"}</button>
            {businessSaved && <p role="status">Company rules saved.</p>}
          </form>
          </details>
        )}
      </section>
      <section className="panel padded setup-panel">
        <h2>Company and master data</h2>
        <p>
          {companies.length} companies configured. Create a company on the
          Dashboard, Customers, or Products page, then import its{" "}
          <Link to="/customers">customers</Link> and{" "}
          <Link to="/products">products</Link> from Excel.
        </p>
        <p>
          Export column mappings are managed under{" "}
          <Link to="/export-profiles">Export profiles</Link>. ERP
          synchronization is planned for a future milestone.
        </p>
      </section>
    </>
  );
}
