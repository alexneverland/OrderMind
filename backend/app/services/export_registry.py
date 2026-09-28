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


def extract_source_field_value(field_name: str, order: Order, line: OrderLine) -> Any:
    """
    Safely resolves whitelisted source field without arbitrary attribute access.
    """
    customer = order.customer
    product = line.matched_product

    resolvers = {
        # Order
        "order.id": lambda: order.id,
        "order.order_number": lambda: order.order_number,
        "order.created_at": lambda: order.created_at.strftime("%Y-%m-%d %H:%M:%S") if order.created_at else "",
        "order.approved_at": lambda: order.approved_at.strftime("%Y-%m-%d %H:%M:%S") if order.approved_at else "",
        "order.overall_confidence": lambda: round(order.overall_confidence, 2),

        # Customer
        "customer.id": lambda: customer.id if customer else "",
        "customer.customer_code": lambda: customer.customer_code if customer else "",
        "customer.customer_name": lambda: customer.customer_name if customer else "",
        "customer.email": lambda: customer.email or "" if customer else "",
        "customer.phone": lambda: customer.phone or "" if customer else "",

        # Line
        "line.line_number": lambda: line.line_number,
        "line.original_text": lambda: line.original_text,
        "line.product_phrase": lambda: line.product_phrase,
        "line.sku": lambda: line.final_sku or (product.sku if product else ""),
        "line.description": lambda: product.description if product else line.product_phrase,
        "line.quantity": lambda: line.final_quantity if line.final_quantity is not None else line.requested_quantity,
        "line.unit": lambda: line.final_unit or line.requested_unit,
        "line.requested_quantity": lambda: line.requested_quantity,
        "line.requested_unit": lambda: line.requested_unit,
        "line.confidence_score": lambda: round(line.confidence_score, 2),
        "line.status": lambda: line.status,

        # Product
        "product.barcode": lambda: product.barcode or "" if product else "",
        "product.sku": lambda: product.sku if product else (line.final_sku or ""),
        "product.description": lambda: product.description if product else line.product_phrase,
    }

    resolver = resolvers.get(field_name)
    if not resolver:
        raise ValueError(f"Unknown source field '{field_name}'. Must be one of: {list(AVAILABLE_SOURCE_FIELDS.keys())}")

    raw_val = resolver()
    return sanitize_formula_injection(raw_val)
