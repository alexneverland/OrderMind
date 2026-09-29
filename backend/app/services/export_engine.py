from typing import Tuple, List, Any
import io
import csv
import json
import re
import hashlib
import math
from datetime import datetime, timezone
import openpyxl
from sqlalchemy.orm import Session

from backend.app.models.order import Order
from backend.app.models.export import ExportProfile, ExportRecord
from backend.app.schemas.workflow import OrderStatus
from backend.app.schemas.export import MappingType
from backend.app.services.export_registry import (
    extract_source_field_value,
    sanitize_formula_injection,
)


class OrderExportError(ValueError):
    """Raised when an order cannot be exported due to status or validation errors."""
    pass


def convert_order_sheet_quantities(
    quantity: float, bonus_quantity: float, unit: str, pieces_per_case: float | None,
) -> Tuple[float, float, str]:
    """Compute the two output quantities used by the four-column order sheet."""
    factor = 1.0
    if unit == "case":
        factor = pieces_per_case
        if factor is None or not math.isfinite(factor) or factor <= 0:
            raise OrderExportError("A valid case packaging ratio is required")
    elif unit not in {"piece", "kg"}:
        raise OrderExportError(f"Unsupported order sheet unit '{unit}'")
    paid = quantity * factor
    gift = bonus_quantity * factor
    if not math.isfinite(paid) or paid <= 0 or not math.isfinite(gift) or gift < 0:
        raise OrderExportError("Invalid converted quantities")
    return paid, gift, "kg" if unit == "kg" else "piece"


def _order_sheet_rows(order: Order, sorted_lines: List[Any]) -> List[List[Any]]:
    """Render approved business values as SKU, description, gift marker, quantity."""
    snapshots = order.approved_snapshot.get("lines", []) if isinstance(order.approved_snapshot, dict) else []
    rows = []
    for index, line in enumerate(sorted_lines):
        item = snapshots[index] if snapshots else {
            "sku": line.final_sku or (line.matched_product.sku if line.matched_product else ""),
            "description": line.matched_product.description if line.matched_product else line.product_phrase,
            "quantity": line.final_quantity if line.final_quantity is not None else line.requested_quantity,
            "unit": line.final_unit or line.requested_unit,
            "bonus_quantity": line.final_bonus_quantity if line.final_bonus_quantity is not None else line.bonus_quantity,
            "pieces_per_case": line.matched_packaging.pieces_per_case if line.matched_packaging else None,
        }
        try:
            paid, gift, _ = convert_order_sheet_quantities(
                item["quantity"], item.get("bonus_quantity") or 0,
                item["unit"], item.get("pieces_per_case"),
            )
        except OrderExportError as exc:
            raise OrderExportError(f"Line {line.line_number}: {exc}") from exc
        sku = sanitize_formula_injection(item["sku"])
        description = sanitize_formula_injection(item["description"])
        rows.append([sku, description, "", paid])
        if gift:
            rows.append([sku, description, "Α", gift])
    return rows


class ExportEngine:
    """
    Renders approved orders into configurable business formats: XLSX, CSV, JSON.
    Enforces approval gate, company isolation, and formula injection protection.
    """

    @classmethod
    def export_order(
        cls,
        db: Session,
        order_id: int,
        profile_id: int,
        preview: bool = False
    ) -> Tuple[bytes, str, str]:
        """
        Exports an order according to the requested ExportProfile.
        Returns:
            (file_bytes, media_type, filename)
        """
        order = db.get(Order, order_id)
        if not order:
            raise ValueError(f"Order with id {order_id} does not exist")

        profile = db.get(ExportProfile, profile_id)
        if not profile:
            raise ValueError(f"Export profile with id {profile_id} does not exist")

        # Company isolation check
        if order.company_id != profile.company_id:
            raise ValueError(
                f"Export profile {profile_id} belongs to company {profile.company_id}, "
                f"not order company {order.company_id}"
            )

        # Export safety approval gate
        if not preview and order.status not in (OrderStatus.APPROVED.value, OrderStatus.EXPORTED.value):
            raise OrderExportError(
                f"Order {order_id} cannot be exported because its status is '{order.status}'. "
                f"Only approved or exported orders can be exported."
            )

        mappings = sorted(profile.field_mappings, key=lambda m: m.column_order)
        if not mappings and profile.format != "order_sheet":
            raise OrderExportError(f"Export profile '{profile.name}' has no column mappings defined.")

        fmt = profile.format.lower().strip()
        is_spreadsheet = fmt in ("excel", "xlsx", "csv", "order_sheet")

        # Build data rows & headers
        # Output headers are sanitized against formula injection (CWE-1236) only for spreadsheet formats
        headers = [
            sanitize_formula_injection(m.output_column_name) if is_spreadsheet else m.output_column_name
            for m in mappings
        ]
        data_rows: List[List[Any]] = []

        # Sort lines by line_number for deterministic output
        sorted_lines = sorted(order.lines, key=lambda l: l.line_number)
        if not preview:
            snapshot = order.approved_snapshot
            if not isinstance(snapshot, dict) or "lines" not in snapshot:
                raise OrderExportError("Approved order has no export snapshot")
            live_identity = [(line.id, line.line_number) for line in sorted_lines]
            snapshot_identity = [(item.get("line_id"), item.get("line_number")) for item in snapshot["lines"]]
            if len(live_identity) != len(snapshot_identity) or any(
                snapshot_id is not None and snapshot_id != live_id or snapshot_number != live_number
                for (live_id, live_number), (snapshot_id, snapshot_number)
                in zip(live_identity, snapshot_identity)
            ):
                raise OrderExportError("Approved order lines differ from export snapshot")

        if fmt == "order_sheet":
            data_rows = _order_sheet_rows(order, sorted_lines)
        else:
            for line in sorted_lines:
                row: List[Any] = []
                for m in mappings:
                    if m.mapping_type == MappingType.CONSTANT.value:
                        val = sanitize_formula_injection(m.constant_value) if is_spreadsheet else m.constant_value
                    else:
                        val = extract_source_field_value(m.source_field, order, line, sanitize=is_spreadsheet)
                    row.append(val)
                data_rows.append(row)

        slug = re.sub(r"[^a-zA-Z0-9_\-]", "_", profile.name.lower()).strip("_")
        now_date = datetime.now(timezone.utc).strftime("%Y%m%d")

        if fmt in ("excel", "xlsx", "order_sheet"):
            wb = openpyxl.Workbook()
            ws = wb.active
            ws.title = "Order"

            if profile.include_header and fmt != "order_sheet":
                ws.append(headers)

            for row in data_rows:
                ws.append(row)

            out = io.BytesIO()
            wb.save(out)
            file_bytes = out.getvalue()
            media_type = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            filename = f"ordermind_order_{order.id}_{slug}_{now_date}.xlsx"

        elif fmt == "csv":
            out = io.StringIO()
            delim = profile.delimiter or ","
            writer = csv.writer(out, delimiter=delim, quoting=csv.QUOTE_MINIMAL)

            if profile.include_header:
                writer.writerow(headers)

            for row in data_rows:
                writer.writerow(row)

            enc = profile.encoding or "utf-8-sig"
            file_bytes = out.getvalue().encode(enc)
            media_type = f"text/csv; charset={enc}"
            filename = f"ordermind_order_{order.id}_{slug}_{now_date}.csv"

        elif fmt == "json":
            json_rows = []
            for row in data_rows:
                row_obj = {header: val for header, val in zip(headers, row)}
                json_rows.append(row_obj)

            file_bytes = json.dumps(json_rows, ensure_ascii=False, indent=2).encode("utf-8")
            media_type = "application/json; charset=utf-8"
            filename = f"ordermind_order_{order.id}_{slug}_{now_date}.json"

        else:
            raise OrderExportError(f"Unsupported format '{profile.format}'.")

        # Update order audit metadata and write export record on final export
        if not preview:
            content_hash = hashlib.sha256(file_bytes).hexdigest()
            export_record = ExportRecord(
                order_id=order.id,
                export_profile_id=profile.id,
                format=fmt,
                filename=filename,
                content_hash=content_hash,
                created_at=datetime.now(timezone.utc)
            )
            db.add(export_record)
            order.version += 1
            order.exported_at = datetime.now(timezone.utc)
            order.status = OrderStatus.EXPORTED.value
            order.last_export_profile_id = profile.id
            db.commit()

        return file_bytes, media_type, filename
