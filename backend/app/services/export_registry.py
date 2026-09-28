from typing import Any, Dict
from datetime import datetime

from backend.app.models.order import Order, OrderLine


AVAILABLE_SOURCE_FIELDS: Dict[str, str] = {
    # Order metadata
    "order.id": "Internal Order ID",
    "order.order_number": "Business Order Number",
    "order.created_at": "Order Creation Timestamp (ISO)",
    "order.approved_at": "Order Approval Timestamp (ISO)",
    "order.overall_confidence": "Overall Order Confidence Score",
    
    # Customer metadata
    "customer.id": "Customer Database ID",
    "customer.customer_code": "Customer Accounting Code",
    "customer.customer_name": "Customer Name",
    "customer.email": "Customer Email",
    "customer.phone": "Customer Phone",
    
    # Line metadata
    "line.line_number": "Line Sequential Number",
    "line.original_text": "Original Verbatim Text from Intake",
    "line.product_phrase": "Extracted Product Phrase",
    "line.sku": "Final Approved Product SKU",
    "line.description": "Final Product Description",
    "line.quantity": "Final Approved Quantity",
    "line.unit": "Final Approved Unit",
    "line.requested_quantity": "Original Requested Quantity",
    "line.requested_unit": "Original Requested Unit",
    "line.confidence_score": "Line Confidence Score",
    "line.status": "Line Review Status",
    
    # Product master metadata
    "product.barcode": "Product Barcode",
    "product.sku": "Product Master SKU",
    "product.description": "Product Master Description",
}


def sanitize_formula_injection(value: Any) -> Any:
    """
    Sanitizes values against CSV/Excel Formula Injection (CWE-1236).
    If a string starts with '=', '+', '-', '@', '\t', '\r', prefix with single quote "'".
    Preserves genuine numeric types (float, int).
    """
    if isinstance(value, str):
        v_stripped = value.strip()
        if v_stripped and v_stripped[0] in ("=", "+", "-", "@", "\t", "\r"):
            return f"'{value}"
    return value


def extract_source_field_value(
    field_name: str,
    order: Order,
    line: OrderLine,
    sanitize: bool = True
) -> Any:
    """
    Safely resolves whitelisted source field without arbitrary attribute access.
    Reads from order.approved_snapshot when available for immutability.
    """
    if field_name not in AVAILABLE_SOURCE_FIELDS:
        raise ValueError(f"Unknown source field '{field_name}'. Must be one of: {list(AVAILABLE_SOURCE_FIELDS.keys())}")

    customer = order.customer
    product = line.matched_product

    # Check snapshot first if order has approved_snapshot
    if order.approved_snapshot and isinstance(order.approved_snapshot, dict):
        snap_order = order.approved_snapshot.get("order", {})
        snap_cust = order.approved_snapshot.get("customer", {})
        snap_lines = order.approved_snapshot.get("lines", [])
        snap_line = next((l for l in snap_lines if l.get("line_number") == line.line_number), None)
    else:
        snap_order = {}
        snap_cust = {}
        snap_line = None

    resolvers = {
        # Order
        "order.id": lambda: snap_order.get("id", order.id),
        "order.order_number": lambda: snap_order.get("order_number", order.order_number),
        "order.created_at": lambda: snap_order.get("created_at") or (order.created_at.strftime("%Y-%m-%d %H:%M:%S") if order.created_at else ""),
        "order.approved_at": lambda: snap_order.get("approved_at") or (order.approved_at.strftime("%Y-%m-%d %H:%M:%S") if order.approved_at else ""),
        "order.overall_confidence": lambda: snap_order.get("overall_confidence", round(order.overall_confidence, 2)),

        # Customer
        "customer.id": lambda: snap_cust.get("id") if (snap_cust and "id" in snap_cust and snap_cust.get("id") is not None) else (customer.id if customer else ""),
        "customer.customer_code": lambda: snap_cust.get("customer_code", customer.customer_code if customer else ""),
        "customer.customer_name": lambda: snap_cust.get("customer_name", customer.customer_name if customer else ""),
        "customer.email": lambda: snap_cust.get("email") or (customer.email or "" if customer else ""),
        "customer.phone": lambda: snap_cust.get("phone") or (customer.phone or "" if customer else ""),

        # Line
        "line.line_number": lambda: snap_line.get("line_number", line.line_number) if snap_line else line.line_number,
        "line.original_text": lambda: snap_line.get("original_text", line.original_text) if snap_line else line.original_text,
        "line.product_phrase": lambda: snap_line.get("product_phrase", line.product_phrase) if snap_line else line.product_phrase,
        "line.sku": lambda: (snap_line.get("sku") if snap_line else None) or line.final_sku or (product.sku if product else ""),
        "line.description": lambda: (snap_line.get("description") if snap_line else None) or (product.description if product else line.product_phrase),
        "line.quantity": lambda: snap_line.get("quantity") if (snap_line and "quantity" in snap_line) else (line.final_quantity if line.final_quantity is not None else line.requested_quantity),
        "line.unit": lambda: (snap_line.get("unit") if snap_line else None) or line.final_unit or line.requested_unit,
        "line.requested_quantity": lambda: snap_line.get("requested_quantity") if (snap_line and "requested_quantity" in snap_line) else line.requested_quantity,
        "line.requested_unit": lambda: (snap_line.get("requested_unit") if snap_line else None) or line.requested_unit,
        "line.confidence_score": lambda: snap_line.get("confidence_score") if (snap_line and "confidence_score" in snap_line) else round(line.confidence_score, 2),
        "line.status": lambda: snap_line.get("status", line.status) if snap_line else line.status,

        # Product
        "product.barcode": lambda: (snap_line.get("barcode") if snap_line else None) or (product.barcode or "" if product else ""),
        "product.sku": lambda: (snap_line.get("sku") if snap_line else None) or (product.sku if product else (line.final_sku or "")),
        "product.description": lambda: (snap_line.get("description") if snap_line else None) or (product.description if product else line.product_phrase),
    }

    raw_val = resolvers[field_name]()
    if sanitize:
        return sanitize_formula_injection(raw_val)
    return raw_val
