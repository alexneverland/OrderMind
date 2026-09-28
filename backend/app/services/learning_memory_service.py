from typing import Optional, Tuple
from datetime import datetime, timezone
from sqlalchemy.orm import Session
from sqlalchemy import select, update

from backend.app.models.customer import Customer
from backend.app.models.product import Product
from backend.app.models.order import Order, OrderLine
from backend.app.models.memory import CustomerProductAlias, HumanCorrection
from backend.app.core.text_normalizer import normalize_text


class AliasConflictError(ValueError):
    """Raised when confirm_match encounters an existing customer alias pointing to a different product."""
    pass


class ConcurrentAliasError(RuntimeError):
    """The alias mapping changed after it was read."""
    pass


class LearningMemoryService:
    """
    Manages customer-specific memory learning loop.
    Records operator confirmations and corrections atomically in SQL.
    Ensures company isolation and memory protection without blind 100% trusting.
    """

    @classmethod
    def _validate_order_context(
        cls,
        db: Session,
        customer: Customer,
        order_id: Optional[int] = None,
        line_id: Optional[int] = None,
    ) -> Optional[int]:
        """
        Validates order and order line consistency:
        - If line_id is provided, verifies that order line exists.
        - If order_id is provided, verifies order exists and belongs to customer and customer's company.
        - If both provided, verifies order_line.order_id == order_id.
        - If only line_id provided, verifies line's parent order belongs to customer and customer's company.
        Returns the resolved order_id.
        """
        resolved_order_id = order_id
        if order_id is not None:
            order = db.get(Order, order_id)
            if not order:
                raise ValueError(f"Order with id {order_id} does not exist")
            if order.company_id != customer.company_id:
                raise ValueError(
                    f"Order {order_id} belongs to company {order.company_id}, "
                    f"not customer company {customer.company_id}"
                )
            if order.customer_id != customer.id:
                raise ValueError(
                    f"Order {order_id} belongs to customer {order.customer_id}, "
                    f"not customer {customer.id}"
                )

        if line_id is not None:
            order_line = db.get(OrderLine, line_id)
            if not order_line:
                raise ValueError(f"Order line with id {line_id} does not exist")
            if order_id is not None and order_line.order_id != order_id:
                raise ValueError(
                    f"Order line {line_id} belongs to order {order_line.order_id}, "
                    f"not order {order_id}"
                )
            if order_id is None:
                parent_order = db.get(Order, order_line.order_id)
                if not parent_order:
                    raise ValueError(f"Parent order {order_line.order_id} for order line {line_id} does not exist")
                if parent_order.company_id != customer.company_id:
                    raise ValueError(
                        f"Order line {line_id} belongs to company {parent_order.company_id}, "
                        f"not customer company {customer.company_id}"
                    )
                if parent_order.customer_id != customer.id:
                    raise ValueError(
                        f"Order line {line_id} belongs to customer {parent_order.customer_id}, "
                        f"not customer {customer.id}"
                    )
                resolved_order_id = order_line.order_id

        return resolved_order_id

    @classmethod
    def confirm_match(
        cls,
        db: Session,
        customer_id: int,
        product_id: int,
        original_phrase: str,
        order_id: Optional[int] = None,
        line_id: Optional[int] = None,
    ) -> CustomerProductAlias:
        """
        Confirms a match for a customer:
        - If CustomerProductAlias exists and matches product: increments confirmed_count, updates last_confirmed_at.
        - If conflict exists (different product): raises AliasConflictError (mutation forbidden via confirm).
        - If none exists: creates new CustomerProductAlias with confirmed_count=1, corrected_count=0.
        """
        customer = db.get(Customer, customer_id)
        if not customer:
            raise ValueError(f"Customer with id {customer_id} does not exist")

        product = db.get(Product, product_id)
        if not product:
            raise ValueError(f"Product with id {product_id} does not exist")

        if product.company_id != customer.company_id:
            raise ValueError(
                f"Product {product_id} belongs to company {product.company_id}, "
                f"not customer company {customer.company_id}"
            )

        norm_phrase = normalize_text(original_phrase)
        if not norm_phrase:
            raise ValueError("Original phrase cannot be empty")

        cls._validate_order_context(db, customer, order_id=order_id, line_id=line_id)

        stmt = select(CustomerProductAlias).where(
            CustomerProductAlias.customer_id == customer_id,
            CustomerProductAlias.normalized_phrase == norm_phrase
        )
        alias = db.execute(stmt).scalar_one_or_none()

        if alias:
            if alias.product_id != product_id:
                raise AliasConflictError(
                    "Existing customer alias points to a different product. Use correct_match() to change the mapping."
                )
            result = db.execute(
                update(CustomerProductAlias)
                .where(CustomerProductAlias.id == alias.id, CustomerProductAlias.product_id == product_id)
                .values(
                    confirmed_count=CustomerProductAlias.confirmed_count + 1,
                    last_confirmed_at=datetime.now(timezone.utc),
                    active=True,
                )
            )
            if result.rowcount != 1:
                raise ConcurrentAliasError("Customer alias changed concurrently; reload and retry")
            db.refresh(alias)
        else:
            alias = CustomerProductAlias(
                customer_id=customer_id,
                product_id=product_id,
                original_phrase=original_phrase.strip(),
                normalized_phrase=norm_phrase,
                confirmed_count=1,
                corrected_count=0,
                active=True,
                last_confirmed_at=datetime.now(timezone.utc)
            )
            db.add(alias)

        db.flush()
        db.refresh(alias)
        return alias

    @classmethod
    def correct_match(
        cls,
        db: Session,
        customer_id: int,
        correct_product_id: int,
        original_phrase: str,
        suggested_product_id: Optional[int] = None,
        order_id: Optional[int] = None,
        line_id: Optional[int] = None,
        notes: Optional[str] = None,
    ) -> Tuple[HumanCorrection, CustomerProductAlias]:
        """
        Atomically records an operator correction:
        - Writes HumanCorrection audit row
        - Updates or creates CustomerProductAlias pointing to correct_product_id
        - Resets confirmed_count to 1 if product changed (never transfers old confirmations!)
        - Increments corrected_count
        """
        customer = db.get(Customer, customer_id)
        if not customer:
            raise ValueError(f"Customer with id {customer_id} does not exist")

        correct_prod = db.get(Product, correct_product_id)
        if not correct_prod:
            raise ValueError(f"Product with id {correct_product_id} does not exist")

        if correct_prod.company_id != customer.company_id:
            raise ValueError(
                f"Product {correct_product_id} belongs to company {correct_prod.company_id}, "
                f"not customer company {customer.company_id}"
            )

        if suggested_product_id is not None:
            suggested_prod = db.get(Product, suggested_product_id)
            if not suggested_prod:
                raise ValueError(f"Suggested product with id {suggested_product_id} does not exist")
            if suggested_prod.company_id != customer.company_id:
                raise ValueError(
                    f"Suggested product {suggested_product_id} belongs to company {suggested_prod.company_id}, "
                    f"not customer company {customer.company_id}"
                )

        resolved_order_id = cls._validate_order_context(db, customer, order_id=order_id, line_id=line_id)

        norm_phrase = normalize_text(original_phrase)
        if not norm_phrase:
            raise ValueError("Original phrase cannot be empty")

        try:
            # 1. Audit log
            correction = HumanCorrection(
                customer_id=customer_id,
                order_id=resolved_order_id,
                order_line_id=line_id,
                original_phrase=original_phrase.strip(),
                suggested_product_id=suggested_product_id,
                correct_product_id=correct_product_id,
                notes=notes
            )
            db.add(correction)

            # 2. Update or create alias
            stmt = select(CustomerProductAlias).where(
                CustomerProductAlias.customer_id == customer_id,
                CustomerProductAlias.normalized_phrase == norm_phrase
            )
            alias = db.execute(stmt).scalar_one_or_none()

            if alias:
                previous_product_id = alias.product_id
                result = db.execute(
                    update(CustomerProductAlias)
                    .where(
                        CustomerProductAlias.id == alias.id,
                        CustomerProductAlias.product_id == previous_product_id,
                    )
                    .values(
                        product_id=correct_product_id,
                        confirmed_count=(1 if previous_product_id != correct_product_id
                                         else CustomerProductAlias.confirmed_count),
                        corrected_count=CustomerProductAlias.corrected_count + 1,
                        last_confirmed_at=datetime.now(timezone.utc),
                        active=True,
                    )
                )
                if result.rowcount != 1:
                    raise ConcurrentAliasError("Customer alias changed concurrently; reload and retry")
            else:
                alias = CustomerProductAlias(
                    customer_id=customer_id,
                    product_id=correct_product_id,
                    original_phrase=original_phrase.strip(),
                    normalized_phrase=norm_phrase,
                    confirmed_count=1,
                    corrected_count=1,
                    active=True,
                    last_confirmed_at=datetime.now(timezone.utc)
                )
                db.add(alias)

            db.flush()
            db.refresh(correction)
            db.refresh(alias)
            return correction, alias
        except Exception:
            raise
