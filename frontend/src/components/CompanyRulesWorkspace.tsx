import { useEffect, useState } from "react";
import { getCustomers, getProducts } from "../api/masterData";
import { getProfiles } from "../api/exportProfiles";
import {
  analyzeRules, applyRules, createRule, disableRule, getCompanyRules, updateRule,
  type CompanyRule, type QuantityBonusConfig, type RulesProposal, type TriggerMode, type Unit,
} from "../api/rules";
import type { BusinessSettings } from "../api/businessSettings";
import type { Customer, Product, ExportProfile } from "../types";
import { Alert, Spinner } from "./ui";

const emptyConfig: QuantityBonusConfig = {
  trigger: { mode: "per_quantity", quantity: 10, unit: "case" },
  reward: { quantity: 1, unit: "case" },
};

export function describeRule(config: QuantityBonusConfig) {
  const { trigger, reward } = config;
  const condition = trigger.mode === "per_quantity" ? "Every" :
    trigger.mode === "greater_than" ? "Above" : "At least";
  const label = (quantity: number, unit: Unit) => unit === "kg" || quantity === 1 ? unit : `${unit}s`;
  return `${condition} ${trigger.quantity} ${label(trigger.quantity, trigger.unit)} → +${reward.quantity} free ${label(reward.quantity, reward.unit)}`;
}

export function CompanyRulesWorkspace({ companyId, business, onBusinessChanged, onEditSettings }: {
  companyId: number;
  business: BusinessSettings;
  onBusinessChanged: (value: BusinessSettings) => void;
  onEditSettings: () => void;
}) {
  const [description, setDescription] = useState("");
  const [proposal, setProposal] = useState<RulesProposal | null>(null);
  const [rules, setRules] = useState<CompanyRule[]>([]);
  const [products, setProducts] = useState<Product[]>([]);
  const [customers, setCustomers] = useState<Customer[]>([]);
  const [profiles, setProfiles] = useState<ExportProfile[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [editId, setEditId] = useState<number | null>(null);
  const [promotionEditorOpen, setPromotionEditorOpen] = useState(false);
  const [config, setConfig] = useState<QuantityBonusConfig>(emptyConfig);
  const [productId, setProductId] = useState<number | null>(null);
  const [customerId, setCustomerId] = useState<number | null>(null);

  useEffect(() => {
    let active = true;
    setRules([]); setProducts([]); setCustomers([]); setProfiles([]); setProposal(null);
    setDescription(""); setError(""); setMessage(""); setEditId(null); setPromotionEditorOpen(false);
    void Promise.all([getCompanyRules(companyId), getProducts(companyId), getCustomers(companyId)])
      .then(([nextRules, nextProducts, nextCustomers]) => {
        if (active) { setRules(nextRules); setProducts(nextProducts); setCustomers(nextCustomers); }
      })
      .catch((cause) => { if (active) setError((cause as Error).message); });
    void getProfiles(companyId).then((nextProfiles) => { if (active) setProfiles(nextProfiles); }).catch(() => {});
    return () => { active = false; };
  }, [companyId]);

  const refresh = async () => setRules(await getCompanyRules(companyId));
  const analyze = async () => {
    setBusy(true); setError(""); setMessage(""); setProposal(null);
    try { setProposal(await analyzeRules(companyId, description.trim())); }
    catch (cause) { setError((cause as Error).message); }
    finally { setBusy(false); }
  };
  const changeProposedRule = (index: number, key: "product_id" | "customer_id", value: number | null) => {
    if (!proposal) return;
    setProposal({ ...proposal, quantity_rules: proposal.quantity_rules.map((rule, i) => i === index ? { ...rule, [key]: value } : rule) });
  };
  const unresolved = proposal?.quantity_rules.some((rule) =>
    (rule.product_reference && !rule.product_id) || (rule.customer_reference && !rule.customer_id)) ||
    Boolean(proposal?.export_patch && !proposal.export_patch.profile_id) ||
    Boolean(proposal?.export_patch?.palletization?.dedicated_groups.some((group) => group.products.some((product) => !product.product_id)));
  const choosePalletProduct = (groupIndex: number, productIndex: number, productId: number | null) => {
    if (!proposal?.export_patch?.palletization) return;
    const palletization = proposal.export_patch.palletization;
    const groups = palletization.dedicated_groups.map((group, gi) => gi !== groupIndex ? group : {
      ...group, products: group.products.map((product, pi) => pi === productIndex ? { ...product, product_id: productId } : product),
    });
    setProposal({ ...proposal, export_patch: { ...proposal.export_patch, palletization: { ...palletization, dedicated_groups: groups } } });
  };
  const hasSupported = Boolean(proposal && (
    Object.values(proposal.settings_patch).some((value) => value !== null) ||
    proposal.quantity_rules.length || proposal.export_patch));
  const apply = async () => {
    if (!proposal) return;
    setBusy(true); setError(""); setMessage("");
    try {
      const result = await applyRules(companyId, proposal);
      onBusinessChanged(result.settings);
      await refresh();
      void getProfiles(companyId).then(setProfiles).catch(() => {});
      setProposal(null);
      setMessage("Rules applied to this company.");
    } catch (cause) { setError((cause as Error).message); }
    finally { setBusy(false); }
  };
  const savePromotion = async (event: React.FormEvent) => {
    event.preventDefault();
    setBusy(true); setError(""); setMessage("");
    try {
      if (editId) await updateRule(companyId, editId, { configuration: config, product_id: productId, customer_id: customerId });
      else await createRule(companyId, { rule_type: "quantity_bonus", enabled: true, product_id: productId, customer_id: customerId, configuration: config });
      await refresh();
      setEditId(null); setPromotionEditorOpen(false); setConfig(emptyConfig); setProductId(null); setCustomerId(null);
      setMessage("Promotion saved.");
    } catch (cause) { setError((cause as Error).message); }
    finally { setBusy(false); }
  };
  const startEdit = (rule: CompanyRule) => {
    setEditId(rule.id); setPromotionEditorOpen(true); setConfig(rule.configuration); setProductId(rule.product_id); setCustomerId(rule.customer_id);
  };
  const disable = async (id: number) => {
    setBusy(true); setError("");
    try { await disableRule(companyId, id); await refresh(); }
    catch (cause) { setError((cause as Error).message); }
    finally { setBusy(false); }
  };
  const enable = async (id: number) => {
    setBusy(true); setError("");
    try { await updateRule(companyId, id, { enabled: true }); await refresh(); }
    catch (cause) { setError((cause as Error).message); }
    finally { setBusy(false); }
  };
  const updateTrigger = (patch: Partial<QuantityBonusConfig["trigger"]>) =>
    setConfig({ ...config, trigger: { ...config.trigger, ...patch } });
  const updateReward = (patch: Partial<QuantityBonusConfig["reward"]>) =>
    setConfig({ ...config, reward: { ...config.reward, ...patch } });

  return <div className="stack-form">
    <h3>Tell OrderMind how orders work in this company</h3>
    <p>AI proposes supported rules for your review. Nothing changes until you select Apply rules. Orders execute saved rules deterministically.</p>
    <label>Describe company rules
      <textarea rows={5} maxLength={6000} value={description} onChange={(event) => setDescription(event.target.value)}
        placeholder={"When customers write 10+1, the 1 is free.\nIf no unit is written, use pieces.\nEvery 10 cases of SKU 1234 gives 1 free case."} />
    </label>
    <button className="button primary" type="button" disabled={busy || description.trim().length < 3} onClick={() => void analyze()}>
      {busy ? <Spinner /> : "Analyze rules"}
    </button>
    <Alert message={error} />
    {message && <p role="status">{message}</p>}
    {proposal && <section className="panel padded" aria-label="Rule proposal">
      <h3>I understood</h3>
      {Object.entries(proposal.settings_patch).filter(([, value]) => value !== null).map(([key, value]) =>
        <p key={key}>✓ {key.replaceAll("_", " ")}: {String(value).replaceAll("_", " ")}</p>)}
      {proposal.quantity_rules.map((rule, index) => <div key={index} className="candidate">
        <strong>✓ {describeRule(rule.configuration)}</strong>
        {rule.product_reference && <label>Product {rule.product_reference}
          <select value={rule.product_id ?? ""} onChange={(event) => changeProposedRule(index, "product_id", Number(event.target.value) || null)}>
            <option value="">Select matching product</option>
            {rule.product_candidates.map((candidate) => <option key={candidate.id} value={candidate.id}>{candidate.label}</option>)}
          </select>
        </label>}
        {rule.customer_reference && <label>Customer {rule.customer_reference}
          <select value={rule.customer_id ?? ""} onChange={(event) => changeProposedRule(index, "customer_id", Number(event.target.value) || null)}>
            <option value="">Select matching customer</option>
            {rule.customer_candidates.map((candidate) => <option key={candidate.id} value={candidate.id}>{candidate.label}</option>)}
          </select>
        </label>}
      </div>)}
      {proposal.export_patch && <div className="candidate">
        <strong>✓ Order-sheet export convention</strong>
        <p>{Object.entries(proposal.export_patch).filter(([key, value]) => key !== "profile_id" && key !== "palletization" && value != null)
          .map(([key, value]) => `${key.replaceAll("_", " ")}: ${value}`).join(" · ")}</p>
        {proposal.export_patch.palletization && <div className="stack-form">
          <strong>Pallet proposal</strong>
          <p>Automatic: {proposal.export_patch.palletization.automatic_pallets.max_weight_kg ?? "—"} kg · {proposal.export_patch.palletization.automatic_pallets.max_rows ?? "—"} {proposal.export_patch.palletization.automatic_pallets.row_count_mode.replaceAll("_", " ")} · {proposal.export_patch.palletization.output.layout.replaceAll("_", " ")}</p>
          {proposal.export_patch.palletization.dedicated_groups.map((group, gi) => <div key={gi}>
            <strong>{group.name}</strong>
            {group.products.map((product, pi) => <label key={pi}>Product {product.reference}
              <select value={product.product_id ?? ""} onChange={(event) => choosePalletProduct(gi, pi, Number(event.target.value) || null)}>
                <option value="">Select matching product</option>
                {product.candidates.map((candidate) => <option key={candidate.id} value={candidate.id}>{candidate.label}</option>)}
              </select>
            </label>)}
          </div>)}
        </div>}
        <label>Export profile
          <select value={proposal.export_patch.profile_id ?? ""} onChange={(event) => setProposal({ ...proposal, export_patch: { ...proposal.export_patch!, profile_id: Number(event.target.value) || null } })}>
            <option value="">Select order-sheet profile</option>
            {proposal.export_profile_candidates.map((candidate) => <option key={candidate.id} value={candidate.id}>{candidate.label}</option>)}
          </select>
        </label>
      </div>}
      {proposal.unsupported_rules.map((item, index) => <p key={index} role="note">Unsupported: {item.text} — {item.reason}</p>)}
      <div className="line-actions">
        <button className="button primary" disabled={busy || unresolved || !hasSupported} onClick={() => void apply()}>Apply rules</button>
        <button className="button" onClick={() => setProposal(null)}>Cancel</button>
      </div>
    </section>}
    <div>
      <h3>Active rules</h3>
      <div className="candidate"><strong>Bonus syntax</strong><p>{business.bonus_enabled ? business.bonus_expression_mode.replaceAll("_", " ") : "Disabled"}</p><button className="button" onClick={onEditSettings}>Edit company setting</button></div>
      <div className="candidate"><strong>Missing unit</strong><p>{business.unitless_order_behavior.replaceAll("_", " ")}</p><button className="button" onClick={onEditSettings}>Edit company setting</button></div>
      <div className="candidate"><strong>Packaging conversion</strong><p>{business.allow_packaging_conversion ? "Allowed using catalog ratios" : "Disabled"}</p><button className="button" onClick={onEditSettings}>Edit company setting</button></div>
      <div className="candidate"><strong>Learn unit corrections</strong><p>{business.learn_unit_preferences ? "Enabled" : "Disabled"}</p><button className="button" onClick={onEditSettings}>Edit company setting</button></div>
      {profiles.filter((profile) => profile.format === "order_sheet" && profile.palletization?.enabled).map((profile) => <div className="candidate" key={`pallet-${profile.id}`}>
        <strong>Pallet planning · {profile.name}</strong>
        {profile.palletization.dedicated_groups.map((group, index) => <p key={index}>{group.name}: {group.product_ids.map((id) => products.find((product) => product.id === id)?.sku ?? `#${id}`).join(", ")}</p>)}
        <p>Automatic: {profile.palletization.automatic_pallets.max_weight_kg ?? "—"} kg · {profile.palletization.automatic_pallets.max_rows ?? "—"} {profile.palletization.automatic_pallets.row_count_mode.replaceAll("_", " ")}</p>
        <p>Output: {profile.palletization.output.layout.replaceAll("_", " ")}</p>
      </div>)}
      {rules.filter((rule) => rule.enabled).map((rule) => <div key={rule.id} className="candidate">
        <strong>Promotion · {describeRule(rule.configuration)}</strong>
        <p>Applies to: {rule.product_id ? products.find((product) => product.id === rule.product_id)?.sku || `product #${rule.product_id}` : "all products"}
          {rule.customer_id ? ` · ${customers.find((customer) => customer.id === rule.customer_id)?.customer_name || `customer #${rule.customer_id}`}` : ""}</p>
        <div className="line-actions"><button className="button" onClick={() => startEdit(rule)}>Edit</button>
          <button className="button subtle" disabled={busy} onClick={() => void disable(rule.id)}>Disable</button></div>
      </div>)}
      {rules.some((rule) => !rule.enabled) && <details>
        <summary>Disabled promotions</summary>
        {rules.filter((rule) => !rule.enabled).map((rule) => <div key={rule.id} className="candidate">
          <strong>{describeRule(rule.configuration)}</strong>
          <button className="button" disabled={busy} onClick={() => void enable(rule.id)}>Enable</button>
        </div>)}
      </details>}
    </div>
    <details open={promotionEditorOpen} onToggle={(event) => setPromotionEditorOpen(event.currentTarget.open)}>
      <summary>{editId ? `Edit promotion #${editId}` : "Add promotion manually"}</summary>
      <form className="stack-form" onSubmit={(event) => void savePromotion(event)}>
        <label>Trigger mode<select value={config.trigger.mode} onChange={(event) => updateTrigger({ mode: event.target.value as TriggerMode })}>
          <option value="per_quantity">Every N</option><option value="greater_than">Above N</option><option value="greater_or_equal">At least N</option>
        </select></label>
        <label>Trigger quantity<input type="number" min="0.000001" step="any" required value={config.trigger.quantity} onChange={(event) => updateTrigger({ quantity: Number(event.target.value) })} /></label>
        <label>Unit<select value={config.trigger.unit} onChange={(event) => { const unit = event.target.value as Unit; updateTrigger({ unit }); updateReward({ unit }); }}>
          <option value="piece">Piece</option><option value="case">Case</option><option value="kg">Kg</option><option value="pallet">Pallet</option>
        </select></label>
        <label>Free quantity<input type="number" min="0.000001" step="any" required value={config.reward.quantity} onChange={(event) => updateReward({ quantity: Number(event.target.value) })} /></label>
        <label>Product scope<select value={productId ?? ""} onChange={(event) => setProductId(Number(event.target.value) || null)}>
          <option value="">All products</option>{products.map((product) => <option key={product.id} value={product.id}>{product.sku} · {product.description}</option>)}
        </select></label>
        <label>Customer scope<select value={customerId ?? ""} onChange={(event) => setCustomerId(Number(event.target.value) || null)}>
          <option value="">All customers</option>{customers.map((customer) => <option key={customer.id} value={customer.id}>{customer.customer_code} · {customer.customer_name}</option>)}
        </select></label>
        <button className="button primary" disabled={busy || config.trigger.quantity <= 0 || config.reward.quantity <= 0}>Save promotion</button>
      </form>
    </details>
  </div>;
}
