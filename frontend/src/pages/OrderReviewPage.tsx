import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { Link, useParams } from "react-router-dom";
import {
  approveOrder,
  confirmLine,
  correctLine,
  exportOrder,
  getOrder,
  getPalletPreview,
  type PalletPreview,
  updateFinalValues,
} from "../api/orders";
import { getProducts } from "../api/masterData";
import { getProfiles } from "../api/exportProfiles";
import { saveDownload } from "../api/client";
import { useAsync } from "../hooks/useAsync";
import {
  Alert,
  Badge,
  dateTime,
  Empty,
  percent,
  Spinner,
} from "../components/ui";
import type { ExportProfile, Order, OrderLine, Product } from "../types";

const units = ["piece", "case", "kg", "pallet"];
const readyStatuses = new Set(["auto_accepted", "confirmed", "corrected"]);

function ProductDialog({
  order,
  line,
  onClose,
  onDone,
}: {
  order: Order;
  line: OrderLine;
  onClose: () => void;
  onDone: () => Promise<void>;
}) {
  const [query, setQuery] = useState("");
  const [products, setProducts] = useState<Product[]>([]);
  const [chosen, setChosen] = useState<number | null>(null);
  const [notes, setNotes] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const searchGeneration = useRef(0);
  const search = async () => {
    const current = ++searchGeneration.current;
    setBusy(true);
    setError("");
    try {
      const results = await getProducts(order.company_id, query);
      if (current === searchGeneration.current) {
        setProducts(results);
        setChosen(null);
      }
    } catch (e) {
      if (current === searchGeneration.current) setError((e as Error).message);
    } finally {
      if (current === searchGeneration.current) setBusy(false);
    }
  };
  const submit = async () => {
    if (!chosen) return;
    setBusy(true);
    setError("");
    try {
      await correctLine(order, line.id, chosen, notes);
      await onDone();
      onClose();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };
  return (
    <div
      className="modal-backdrop"
      onMouseDown={() => {
        if (!busy) onClose();
      }}
    >
      <section
        role="dialog"
        aria-modal="true"
        aria-label="Change product"
        className="modal"
        onMouseDown={(e) => e.stopPropagation()}
      >
        <div className="modal-head">
          <div>
            <div className="eyebrow">LINE {line.line_number}</div>
            <h2>Choose product</h2>
          </div>
          <button
            onClick={onClose}
            className="icon-button"
            aria-label="Close"
            disabled={busy}
          >
            ×
          </button>
        </div>
        <p className="muted">
          Search the company catalog by SKU, description or barcode.
        </p>
        <Alert message={error} />
        <form
          className="search-form"
          onSubmit={(e) => {
            e.preventDefault();
            void search();
          }}
        >
          <input
            aria-label="Search products"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            autoFocus
            placeholder="SKU, description or barcode"
          />
          <button className="button" disabled={busy}>
            Search
          </button>
        </form>
        <div className="product-results">
          {products.map((product) => (
            <label
              className={`product-option ${chosen === product.id ? "chosen" : ""}`}
              key={product.id}
            >
              <input
                type="radio"
                name="product"
                checked={chosen === product.id}
                onChange={() => setChosen(product.id)}
              />
              <span>
                <strong>{product.sku}</strong> · {product.description}
                <small>
                  {product.barcode || "No barcode"} · {product.unit}
                </small>
              </span>
            </label>
          ))}
          {!products.length && (
            <p className="muted">Search to see available products.</p>
          )}
        </div>
        <label>
          Correction note (optional)
          <textarea
            rows={2}
            value={notes}
            onChange={(e) => setNotes(e.target.value)}
          />
        </label>
        <div className="modal-actions">
          <button className="button" onClick={onClose} disabled={busy}>
            Cancel
          </button>
          <button
            className="button primary"
            disabled={!chosen || busy}
            onClick={() => void submit()}
          >
            {busy ? <Spinner /> : "Correct match"}
          </button>
        </div>
      </section>
    </div>
  );
}

function LineCard({
  order,
  line,
  previewProfile,
  refresh,
  setError,
}: {
  order: Order;
  line: OrderLine;
  previewProfile: ExportProfile | null;
  refresh: () => Promise<void>;
  setError: (value: string) => void;
}) {
  const [dialog, setDialog] = useState(false);
  const [editing, setEditing] = useState(false);
  const [quantity, setQuantity] = useState(
    String(line.final_quantity ?? line.requested_quantity),
  );
  const [unit, setUnit] = useState(line.final_unit ?? (line.requested_unit === "unknown" ? "unknown" : line.requested_unit));
  const [bonusQuantity, setBonusQuantity] = useState(String(line.final_bonus_quantity ?? (line.bonus_quantity || line.calculated_bonus_quantity || 0)));
  const [bonusEdited, setBonusEdited] = useState(false);
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    setQuantity(String(line.final_quantity ?? line.requested_quantity));
    setUnit(line.final_unit ?? (line.requested_unit === "unknown" ? "unknown" : line.requested_unit));
    setBonusQuantity(String(line.final_bonus_quantity ?? (line.bonus_quantity || line.calculated_bonus_quantity || 0)));
    setBonusEdited(false);
  }, [line]);
  const editable = order.status === "pending_review";
  const act = async (action: () => Promise<unknown>) => {
    setBusy(true);
    setError("");
    try {
      await action();
      await refresh();
      return true;
    } catch (e) {
      setError((e as Error).message);
      return false;
    } finally {
      setBusy(false);
    }
  };
  const finalQuantity = line.final_quantity ?? line.requested_quantity;
  const finalUnit = line.final_unit ?? line.requested_unit;
  const finalBonusQuantity = line.final_bonus_quantity ?? (line.bonus_quantity || line.calculated_bonus_quantity || 0);
  const changed =
    finalQuantity !== line.requested_quantity ||
    (finalUnit !== null && finalUnit !== line.requested_unit) ||
    finalBonusQuantity !== (line.bonus_quantity || line.calculated_bonus_quantity || 0);
  return (
    <article className="line-card" data-order-line-id={line.id}>
      <div className="line-top">
        <div>
          <span className="eyebrow">
            LINE {String(line.line_number).padStart(2, "0")}
          </span>
          <h3>{line.matched_product?.description || line.product_phrase}</h3>
          <div className="muted">
            {line.matched_product ? (
              <>
                <strong>SKU {line.matched_product.sku}</strong>
                {line.matched_product.barcode &&
                  ` · ${line.matched_product.barcode}`}
              </>
            ) : (
              "No product selected"
            )}
          </div>
        </div>
        <Badge status={line.status} />
      </div>
      <div className="line-grid">
        <div>
          <span className="field-label">Original</span>
          <q>{line.original_text}</q>
        </div>
        <div>
          <span className="field-label">Requested</span>
          <strong>
            {line.requested_quantity} {line.unit_explicit ? (line.requested_unit === "unknown" ? line.raw_unit || "unknown unit" : line.requested_unit) : "· unit not specified"}
          </strong>
          {!!line.bonus_quantity && <small> + {line.bonus_quantity} δώρο</small>}
        </div>
        {line.promotion_result && <div>
          <span className="field-label">Promotion</span>
          <strong>+{line.calculated_bonus_quantity || 0} {finalUnit} free</strong>
          <small>{line.promotion_result.explanation}</small>
          {line.promotion_result.requires_review && <small>Review required: choose the final free quantity.</small>}
        </div>}
        <div>
          <span className="field-label">
            Final {changed && <em>changed</em>}
          </span>
          <strong>
            {finalQuantity} {finalUnit === "unknown" || !finalUnit ? "· unit not set" : finalUnit}
          </strong>
          {!!finalBonusQuantity && <small> + {finalBonusQuantity} δώρο</small>}
        </div>
        <div>
          <span className="field-label">Ποσότητα εξαγωγής {previewProfile?.name || ""}</span>
          {previewProfile && line.order_sheet_paid_quantity != null ? (
            <>
              <strong>{line.order_sheet_paid_quantity} {line.order_sheet_unit === "kg" ? "κιλά" : line.order_sheet_unit === "case" ? "κιβώτια" : "τεμάχια"}</strong>
              {!!line.order_sheet_bonus_quantity && (
                <small> + {line.order_sheet_bonus_quantity} {line.order_sheet_unit === "kg" ? "κιλά" : line.order_sheet_unit === "case" ? "κιβώτια" : "τεμάχια"} δώρο (χωριστή γραμμή {line.order_sheet_bonus_marker})</small>
              )}
            </>
          ) : (
            <small>{previewProfile ? line.order_sheet_conversion_error || "Η μετατροπή δεν είναι ακόμη διαθέσιμη" : "Επίλεξε προφίλ 4 στηλών για προεπισκόπηση"}</small>
          )}
        </div>
        <div>
          <span className="field-label">Confidence</span>
          <strong>{percent(line.confidence_score)}</strong>
        </div>
      </div>
      {!!line.confidence_reasons.length && (
        <details className="line-details">
          <summary>Why this match?</summary>
          <ul>
            {line.confidence_reasons.map((reason, i) => (
              <li key={i}>{reason}</li>
            ))}
          </ul>
        </details>
      )}
      {!!line.candidates.length && (
        <details className="line-details">
          <summary>Alternative matches ({line.candidates.length})</summary>
          <div className="candidate-list">
            {line.candidates.map((c) => (
              <div key={c.id} className="candidate">
                <strong>{c.product?.sku || `Product #${c.product_id}`}</strong>{" "}
                · {c.product?.description || "Unknown product"}
                <span>
                  {percent(c.score)} · {c.match_type}
                </span>
                <small>{c.explanation}</small>
              </div>
            ))}
          </div>
        </details>
      )}
      {editable && (
        <div className="line-actions">
          {line.status === "needs_review" && line.matched_product_id && (
            <button
              className="button primary"
              disabled={busy}
              onClick={() => void act(() => confirmLine(order, line.id))}
            >
              {busy ? <Spinner /> : "Confirm match"}
            </button>
          )}
          <button
            className="button"
            disabled={busy}
            onClick={() => setDialog(true)}
          >
            {line.status === "unresolved" ? "Choose product" : "Change product"}
          </button>
          <button
            className="button subtle"
            disabled={busy}
            onClick={() => setEditing((v) => !v)}
          >
            Edit final values
          </button>
        </div>
      )}
      {editable && editing && (
        <form
          className="inline-edit"
          onSubmit={(e) => {
            e.preventDefault();
            const basisChanged = Number(quantity) !== finalQuantity || unit !== finalUnit;
            const operatorChoseBonus = bonusEdited || (!basisChanged && line.promotion_result?.requires_review && line.final_bonus_quantity == null);
            void act(() =>
              updateFinalValues(order.id, line.id, Number(quantity), unit, operatorChoseBonus ? Number(bonusQuantity) : undefined),
            ).then((success) => {
              if (success) setEditing(false);
            });
          }}
        >
          <label>
            Final quantity
            <input
              type="number"
              min="0.000001"
              step="any"
              value={quantity}
              onChange={(e) => setQuantity(e.target.value)}
              required
            />
          </label>
          <label>
            Final unit
            <select value={unit} onChange={(e) => setUnit(e.target.value)}>
              {unit === "unknown" && <option value="unknown" disabled>Choose unit</option>}
              {units.map((u) => (
                <option key={u} value={u}>
                  {u}
                </option>
              ))}
            </select>
          </label>
          <label>
            Ποσότητα δώρου
            <input type="number" min="0" step="any" value={bonusQuantity}
              onChange={(e) => { setBonusQuantity(e.target.value); setBonusEdited(true); }} required />
          </label>
          <button
            className="button primary"
            disabled={busy || Number(quantity) <= 0 || unit === "unknown"}
          >
            Save values
          </button>
        </form>
      )}
      {dialog && (
        <ProductDialog
          order={order}
          line={line}
          onClose={() => setDialog(false)}
          onDone={refresh}
        />
      )}
    </article>
  );
}

export function OrderReviewPage() {
  const { orderId } = useParams();
  const id = Number(orderId);
  const [previewProfileId, setPreviewProfileId] = useState("");
  const [profileId, setProfileId] = useState("");
  const {
    data: loadedOrder,
    error: loadError,
    loading,
    refresh,
  } = useAsync(() => getOrder(id, previewProfileId ? Number(previewProfileId) : undefined), [id, previewProfileId], true);
  const order = loadedOrder?.id === id ? loadedOrder : null;
  const scrollAnchor = useRef<{ lineId: string; top: number } | null>(null);
  const refreshAtCurrentLine = async () => {
    const cards = Array.from(document.querySelectorAll<HTMLElement>("[data-order-line-id]"));
    const visible = cards.find((card) => {
      const rect = card.getBoundingClientRect();
      return rect.bottom > 0 && rect.top < window.innerHeight;
    });
    const anchor = visible ?? cards.at(-1);
    if (anchor) {
      scrollAnchor.current = {
        lineId: anchor.dataset.orderLineId ?? "",
        top: anchor.getBoundingClientRect().top,
      };
    }
    await refresh();
  };
  useLayoutEffect(() => {
    const anchor = scrollAnchor.current;
    if (!anchor || !order) return;
    const card = document.querySelector<HTMLElement>(`[data-order-line-id="${anchor.lineId}"]`);
    if (card) window.scrollBy(0, card.getBoundingClientRect().top - anchor.top);
    scrollAnchor.current = null;
  }, [order]);
  const { data: profiles } = useAsync(
    () => (order ? getProfiles(order.company_id) : Promise.resolve([])),
    [order?.company_id],
  );
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [palletPreview, setPalletPreview] = useState<PalletPreview | null>(null);
  useEffect(() => setPalletPreview(null), [profileId, order?.id, order?.status]);
  useEffect(() => {
    if (!previewProfileId) {
      const first = profiles?.find((p) => p.format === "order_sheet");
      if (first) setPreviewProfileId(String(first.id));
    }
  }, [profiles, previewProfileId]);
  const [confirmApproval, setConfirmApproval] = useState(false);
  if (loading && !order)
    return (
      <div className="center">
        <Spinner />
      </div>
    );
  if (!order)
    return (
      <>
        <Alert message={loadError} />
        <Empty>
          Order not found. <Link to="/orders">Back to orders</Link>
        </Empty>
      </>
    );
  const ready = order.lines.filter((l) => readyStatuses.has(l.status)).length;
  const needsReview = order.lines.filter(
    (l) => l.status === "needs_review",
  ).length;
  const unresolved = order.lines.filter(
    (l) => l.status === "unresolved",
  ).length;
  const previewProfile = profiles?.find((p) => p.id === Number(previewProfileId) && p.format === "order_sheet") || null;
  const approve = async () => {
    setBusy(true);
    setError("");
    try {
      await approveOrder(order.id);
      await refreshAtCurrentLine();
      setConfirmApproval(false);
    } catch (e) {
      setConfirmApproval(false);
      try {
        await refreshAtCurrentLine();
      } catch {
        // The loader displays its own error if refreshing also fails.
      }
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };
  const exportNow = async () => {
    if (!profileId) return;
    setBusy(true);
    setError("");
    try {
      const result = await exportOrder(order.id, Number(profileId));
      saveDownload(result.blob, result.filename);
      await refreshAtCurrentLine();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };
  return (
    <>
      <div className="breadcrumb">
        <Link to="/orders">Orders</Link> / {order.order_number}
      </div>
      <div className="page-head">
        <div>
          <div className="eyebrow">ORDER REVIEW</div>
          <h1>{order.order_number}</h1>
          <p>
            {order.customer?.customer_code} · {order.customer?.customer_name}{" "}
            <span className="divider">|</span> Created{" "}
            {dateTime(order.created_at)}
          </p>
        </div>
        <Badge status={order.status} />
      </div>
      <Alert message={error} onClose={() => setError("")} />
      <Alert message={loadError} />
      <div className="stats-row">
        <div>
          <span>Total lines</span>
          <strong>{order.lines.length}</strong>
        </div>
        <div>
          <span>Ready</span>
          <strong>{ready}</strong>
        </div>
        <div>
          <span>Needs review</span>
          <strong>{needsReview}</strong>
        </div>
        <div>
          <span>Unresolved</span>
          <strong>{unresolved}</strong>
        </div>
        <div>
          <span>Confidence</span>
          <strong>{percent(order.overall_confidence)}</strong>
        </div>
      </div>
      <div className="review-layout">
        <aside className="panel raw-panel">
          <div className="panel-heading">
            <div className="eyebrow">SOURCE</div>
            <h2>Original order</h2>
            <p>Verbatim customer input</p>
          </div>
          <pre>{order.raw_input}</pre>
        </aside>
        <div className="review-main">
          <div className="section-heading">
            <div>
              <div className="eyebrow">MATCHING</div>
              <h2>Review lines</h2>
            </div>
            <span className="muted">{order.lines.length} lines</span>
          </div>
          {!!profiles?.some((p) => p.format === "order_sheet") && (
            <label>Προεπισκόπηση προφίλ 4 στηλών
              <select aria-label="Προεπισκόπηση προφίλ 4 στηλών" value={previewProfile ? previewProfileId : ""}
                onChange={(e) => setPreviewProfileId(e.target.value)}>
                <option value="">Επίλεξε προφίλ</option>
                {profiles.filter((p) => p.format === "order_sheet").map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
              </select>
            </label>
          )}
          {order.lines.map((line) => (
            <LineCard
              key={line.id}
              order={order}
              line={line}
              previewProfile={previewProfile}
              refresh={refreshAtCurrentLine}
              setError={setError}
            />
          ))}
          {order.status === "pending_review" && (
            <section className="panel action-panel">
              <div>
                <h2>Ready to approve?</h2>
                <p>
                  Ready {ready} · Needs review {needsReview} · Unresolved{" "}
                  {unresolved}
                </p>
                {needsReview + unresolved > 0 && (
                  <p className="muted">
                    Resolve every pending line before approval.
                  </p>
                )}
              </div>
              <button
                className="button primary"
                onClick={() => setConfirmApproval(true)}
                disabled={
                  busy || needsReview + unresolved > 0 || !order.lines.length
                }
              >
                Approve order
              </button>
            </section>
          )}
          {(order.status === "approved" || order.status === "exported") && (
            <section className="panel action-panel">
              <div>
                <h2>
                  {order.status === "exported"
                    ? "Re-export order"
                    : "Export order"}
                </h2>
                <p>
                  Approved {dateTime(order.approved_at)}. Business values are
                  read-only.
                </p>
              </div>
              <div className="export-controls">
                <label>
                  Export profile
                  <select
                    aria-label="Export profile"
                    value={profileId}
                    onChange={(e) => setProfileId(e.target.value)}
                  >
                    <option value="">Select profile</option>
                    {profiles?.map((p) => (
                      <option key={p.id} value={p.id}>
                        {p.name} · {p.format.toUpperCase()}
                      </option>
                    ))}
                  </select>
                </label>
                <button
                  className="button primary"
                  disabled={!profileId || busy}
                  onClick={() => void exportNow()}
                >
                  {busy ? <Spinner /> : "Export & download"}
                </button>
                {order.pallet_profile_ids.includes(Number(profileId)) && <button
                  className="button" disabled={busy} onClick={() => {
                    setError("");
                    void getPalletPreview(order.id, Number(profileId)).then(setPalletPreview)
                      .catch((cause) => { setPalletPreview(null); setError((cause as Error).message); });
                  }}>Preview pallets</button>}
              </div>
            </section>
          )}
          {palletPreview && <section className="panel padded" aria-label="Pallet preview">
            <h3>Pallet preview · {palletPreview.layout.replaceAll("_", " ")}</h3>
            {palletPreview.pallets.map((pallet) => <div className="candidate" key={pallet.pallet_number}>
              <strong>Pallet {pallet.pallet_number} · {pallet.type === "dedicated" ? pallet.group_name : "Automatic"}</strong>
              <p>Weight: {pallet.total_weight_kg ?? "unknown"} kg · {pallet.row_count} {palletPreview.row_count_mode.replaceAll("_", " ")}</p>
              {pallet.warnings.map((warning, index) => <p role="alert" key={index}>{warning}</p>)}
              <ul>{pallet.items.map((item, index) => <li key={`${item.source_order_line_id}-${index}`}>
                {item.sku} · {item.description} · {item.paid_quantity} {item.unit}
                {Number(item.bonus_quantity) > 0 ? ` + ${item.bonus_quantity} free` : ""}
                {` · ${item.weight_kg ?? "unknown"} kg · ${item.output_row_count} output rows`}
              </li>)}</ul>
            </div>)}
          </section>}
          {!!order.export_records.length && (
            <section className="panel padded">
              <h3>Export history</h3>
              <ul className="history-list">
                {order.export_records.map((record) => (
                  <li key={record.id}>
                    {dateTime(record.created_at)} · {record.filename} ·{" "}
                    {record.format.toUpperCase()}
                  </li>
                ))}
              </ul>
            </section>
          )}
        </div>
      </div>
      {confirmApproval && (
        <div
          className="modal-backdrop"
          onMouseDown={() => {
            if (!busy) setConfirmApproval(false);
          }}
        >
          <section
            className="modal"
            role="dialog"
            aria-modal="true"
            aria-label="Approve order"
            onMouseDown={(e) => e.stopPropagation()}
          >
            <div className="eyebrow">FINAL REVIEW</div>
            <h2>Approve {order.order_number}?</h2>
            <p>
              Ready {ready} · Needs review {needsReview} · Unresolved{" "}
              {unresolved}
            </p>
            <p className="muted">
              Approval locks the business values used by future exports.
            </p>
            <div className="modal-actions">
              <button
                className="button"
                onClick={() => setConfirmApproval(false)}
                disabled={busy}
              >
                Cancel
              </button>
              <button
                className="button primary"
                disabled={busy}
                onClick={() => void approve()}
              >
                {busy ? <Spinner /> : "Confirm approval"}
              </button>
            </div>
          </section>
        </div>
      )}
    </>
  );
}
