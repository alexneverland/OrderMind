from typing import Tuple, List, Any
import io
import csv
import json
import re
import hashlib
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
        if not mappings:
            raise OrderExportError(f"Export profile '{profile.name}' has no column mappings defined.")

        fmt = profile.format.lower().strip()
        is_spreadsheet = fmt in ("excel", "xlsx", "csv")

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

        if fmt in ("excel", "xlsx"):
            wb = openpyxl.Workbook()
            ws = wb.active
            ws.title = "Order"

            if profile.include_header:
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
