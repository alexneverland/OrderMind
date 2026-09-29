import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import {
  getAISettings,
  saveAISettings,
  type AISettings,
} from "../api/runtimeSettings";
import { useCompany } from "../components/AppShell";
import { Alert, Spinner } from "../components/ui";

export function SettingsPage() {
  const { companies } = useCompany();
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
