from typing import Optional, Tuple
from datetime import datetime, timezone
from sqlalchemy.orm import Session
from sqlalchemy import select

from backend.app.models.customer import Customer
from backend.app.models.product import Product
from backend.app.models.memory import CustomerProductAlias, HumanCorrection
from backend.app.core.text_normalizer import normalize_text


class LearningMemoryService:
    """
    Manages customer-specific memory learning loop.
    Records operator confirmations and corrections atomically in SQL.
    Ensures company isolation and memory protection without blind 100% trusting.
    """

    @classmethod
    def confirm_match(
        cls,
        db: Session,
        customer_id: int,
        product_id: int,
        original_phrase: str,
        order_id: Optional[int] = None,
        line_id: Optional[int] = None
    ) -> CustomerProductAlias:
        """
        Confirms a match for a customer:
        - If CustomerProductAlias exists: increments confirmed_count, updates last_confirmed_at.
        - If conflict exists (different product): updates product_id, increments corrected_count.
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

        stmt = select(CustomerProductAlias).where(
            CustomerProductAlias.customer_id == customer_id,
            CustomerProductAlias.normalized_phrase == norm_phrase
        )
        alias = db.execute(stmt).scalar_one_or_none()

        try:
            if alias:
                if alias.product_id == product_id:
                    alias.confirmed_count += 1
                else:
                    alias.product_id = product_id
                    alias.corrected_count += 1
                alias.last_confirmed_at = datetime.now(timezone.utc)
                alias.active = True
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

            db.commit()
            db.refresh(alias)
            return alias
        except Exception:
            db.rollback()
            raise

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
        notes: Optional[str] = None
    ) -> Tuple[HumanCorrection, CustomerProductAlias]:
        """
        Atomically records an operator correction:
        - Writes HumanCorrection audit row
        - Updates or creates CustomerProductAlias pointing to correct_product_id
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

        norm_phrase = normalize_text(original_phrase)
        if not norm_phrase:
            raise ValueError("Original phrase cannot be empty")

        try:
            # 1. Audit log
            correction = HumanCorrection(
                customer_id=customer_id,
                order_id=order_id,
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
                alias.product_id = correct_product_id
                alias.corrected_count += 1
                alias.last_confirmed_at = datetime.now(timezone.utc)
                alias.active = True
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

            db.commit()
            db.refresh(correction)
            db.refresh(alias)
            return correction, alias
        except Exception:
            db.rollback()
            raise
