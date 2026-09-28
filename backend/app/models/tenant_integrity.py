"""Fill tenant keys for ORM-created child rows; database FKs enforce them."""

from sqlalchemy import event
from sqlalchemy.orm import Session

from backend.app.models.customer import Customer
from backend.app.models.product import Product, Packaging
from backend.app.models.order import Order, OrderLine, MatchCandidate
from backend.app.models.memory import CustomerProductAlias, HumanCorrection
from backend.app.models.export import ExportRecord


@event.listens_for(Session, "before_flush")
def fill_company_keys(session: Session, flush_context, instances) -> None:
    for obj in session.new:
        if getattr(obj, "company_id", None) is not None:
            continue
        parent = None
        if isinstance(obj, Packaging):
            parent = obj.product or session.get(Product, obj.product_id)
        elif isinstance(obj, OrderLine):
            parent = obj.order or session.get(Order, obj.order_id)
        elif isinstance(obj, MatchCandidate):
            parent = obj.order_line or session.get(OrderLine, obj.order_line_id)
        elif isinstance(obj, (CustomerProductAlias, HumanCorrection)):
            parent = obj.customer or session.get(Customer, obj.customer_id)
        elif isinstance(obj, ExportRecord):
            parent = obj.order or session.get(Order, obj.order_id)
        if parent is not None:
            obj.company_id = parent.company_id
