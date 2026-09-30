import io
import math
from decimal import Decimal, InvalidOperation
from typing import Dict, List, Any, Optional
import pandas as pd
from sqlalchemy.orm import Session
from sqlalchemy import select

from backend.app.core.text_normalizer import normalize_text
from backend.app.models.customer import Customer
from backend.app.models.product import Product, Packaging
from backend.app.schemas.imports import (
    HeaderPreviewResponse,
    ImportSummaryResponse,
    RowErrorDetail,
)

# Known synonyms for heuristic column detection
HEURISTIC_SYNONYMS: Dict[str, Dict[str, List[str]]] = {
    "customers": {
        "customer_code": [
            "customer_code", "customercode", "κωδικος", "κωδ_πελατη", "κωδικος_πελατη",
            "code", "cust_code", "id", "customer_id", "κωδικοσ", "κωδ"
        ],
        "customer_name": [
            "customer_name", "customername", "name", "ονομα", "επωνυμια",
            "επωνυμια_πελατη", "εταιρεια", "company", "πελατης", "ονοματεπωνυμο"
        ],
        "email": [
            "email", "e_mail", "mail", "ηλεκτρονικο_ταχυδρομειο", "contact_email", "mail_address"
        ],
        "phone": [
            "phone", "telephone", "τηλεφωνο", "τηλ", "κινητο", "mobile", "tel", "τηλεφωνο1"
        ],
        "active": [
            "active", "ενεργος", "status", "κατασταση", "ενεργη"
        ]
    },
    "products": {
        "kg_per_piece": [
            "kg_per_piece", "gross_kg_per_piece", "gross_weight_per_piece",
            "μικτο_βαρος", "μικτό_βάρος", "μικτο_βαροσ", "μικτο_βαρος_κιλα",
            "μικτό_βάρος_ανά_τεμάχιο", "βαρος_ανα_τεμαχιο",
        ],
        "sku": [
            "sku", "item_code", "itemcode", "product_code", "κωδικος", "κωδ_ειδους",
            "κωδικος_ειδους", "ειδος_κωδικος", "code", "κωδ", "κωδικοσ"
        ],
        "description": [
            "description", "desc", "περιγραφη", "περιγραφη_ειδους", "name",
            "product_name", "ονομασια", "τιτλος", "προιον"
        ],
        "barcode": [
            "barcode", "ean", "ean13", "upc", "μπαρκοουντ", "ραβδοκωδικας", "bar_code"
        ],
        "unit": [
            "unit", "uom", "μ_μ", "μ_μ_", "μοναδα", "μοναδα_μετρησης", "μον_μετρ", "mm", "unit_of_measure"
        ],
        "active": [
            "active", "ενεργο", "status", "κατασταση", "ενεργο_ειδος"
        ]
    },
    "packaging": {
        "product_sku": [
            "product_sku", "sku", "item_code", "κωδικος_ειδους", "κωδικος", "product_code", "κωδ"
        ],
        "package_type": [
            "package_type", "type", "τυπος", "τυπος_συσκευασιας", "συσκευασια", "packaging", "pack_type"
        ],
        "pieces_per_case": [
            "pieces_per_case", "pieces", "τεμαχια_ανα_κιβωτιο", "τεμ_κιβ", "τεμαχια", "qty_per_case", "pcs", "τεμ_συσκ"
        ],
        "weight": [
            "weight", "βαρος", "κιλα", "gross_weight", "net_weight", "βαρος_kg"
        ],
        "unit": [
            "unit", "uom", "μοναδα", "μ_μ", "μον_μετρ"
        ],
        "package_code": [
            "package_code", "pack_code", "κωδικος_συσκευασιας", "κωδ_συσκ", "κωδ_κιβωτιου"
        ],
        "packaging_barcode": [
            "packaging_barcode", "pack_barcode", "barcode_συσκευασιας", "barcode_κιβωτιου", "barcode"
        ]
    }
}

REQUIRED_TARGET_FIELDS = {
    "customers": ["customer_code", "customer_name"],
    "products": ["sku", "description"],
    "packaging": ["product_sku", "package_type", "pieces_per_case"],
}

SUPPORTED_TARGET_FIELDS = {
    "customers": ["customer_code", "customer_name", "email", "phone", "active"],
    "products": ["sku", "description", "barcode", "unit", "active", "kg_per_piece"],
    "packaging": ["product_sku", "package_type", "pieces_per_case", "weight", "unit", "package_code", "packaging_barcode"],
}


def _clean_val(val: Any) -> Any:
    """Helper to convert pandas NaN / float nan to None or clean strings."""
    if val is None:
        return None
    if isinstance(val, float) and (math.isnan(val) or math.isinf(val)):
        return None
    if pd.isna(val):
        return None
    val_str = str(val).strip()
    return val_str if val_str else None


def _clean_bool(val: Any, default: bool = True) -> bool:
    if val is None or pd.isna(val):
        return default
    if isinstance(val, bool):
        return val
    s = str(val).strip().lower()
    if s in ["1", "true", "t", "yes", "y", "ναι", "ν", "active", "ενεργος", "ενεργο"]:
        return True
    if s in ["0", "false", "f", "no", "n", "οχι", "ο", "inactive", "ανενεργος", "ανενεργο"]:
        return False
    return default


def _clean_float(val: Any, default: Optional[float] = None) -> Optional[float]:
    if val is None or pd.isna(val):
        return default
    try:
        return float(val)
    except (ValueError, TypeError):
        return default


class MasterDataService:

    @staticmethod
    def read_excel_dataframe(file_bytes: bytes) -> pd.DataFrame:
        """Reads Excel file into a DataFrame, handling various sheet formats."""
        try:
            df = pd.read_excel(io.BytesIO(file_bytes), engine="openpyxl", dtype=str)
        except Exception:
            # Fallback to default engine
            try:
                df = pd.read_excel(io.BytesIO(file_bytes), dtype=str)
            except Exception:
                raise ValueError("Failed to read Excel file") from None
        
        # Strip string column names
        df.columns = [str(c).strip() for c in df.columns]
        return df

    @classmethod
    def preview_excel(cls, file_bytes: bytes, entity_type: str) -> HeaderPreviewResponse:
        """
        Extracts headers, generates preview rows, and proposes probable column mappings.
        """
        if entity_type not in SUPPORTED_TARGET_FIELDS:
            raise ValueError(f"Unsupported entity type: {entity_type}")

        df = cls.read_excel_dataframe(file_bytes)
        available_columns = list(df.columns)

        # Build candidate suggestions
        synonyms = HEURISTIC_SYNONYMS.get(entity_type, {})
        suggested_mapping: Dict[str, str] = {}
        assigned_cols = set()

        for target_field, candidates in synonyms.items():
            for col in available_columns:
                if col in assigned_cols:
                    continue
                norm_col = normalize_text(col)
                norm_col_clean = norm_col.replace(" ", "_")
                
                matched = False
                for cand in candidates:
                    norm_cand = normalize_text(cand)
                    norm_cand_clean = norm_cand.replace(" ", "_")
                    if (
                        norm_cand == norm_col
                        or norm_cand_clean == norm_col
                        or norm_cand == norm_col_clean
                        or norm_cand_clean == norm_col_clean
                    ):
                        suggested_mapping[target_field] = col
                        assigned_cols.add(col)
                        matched = True
                        break
                if matched:
                    break

        # Preview rows (up to 5 sample rows)
        sample_df = df.head(5).fillna("")
        preview_rows = sample_df.to_dict(orient="records")

        return HeaderPreviewResponse(
            entity_type=entity_type,
            available_columns=available_columns,
            total_preview_rows=len(df),
            preview_rows=preview_rows,
            suggested_mapping=suggested_mapping,
            supported_target_fields=SUPPORTED_TARGET_FIELDS[entity_type],
            required_target_fields=REQUIRED_TARGET_FIELDS[entity_type],
        )

    @classmethod
    def import_customers(
        cls,
        db: Session,
        company_id: int,
        file_bytes: bytes,
        mapping: Dict[str, str]
    ) -> ImportSummaryResponse:
        """
        Imports customers from Excel applying dynamic column mapping with row-level error reporting.
        """
        req_fields = REQUIRED_TARGET_FIELDS["customers"]
        for rf in req_fields:
            if rf not in mapping or not mapping[rf]:
                raise ValueError(f"Missing required mapping for field: '{rf}'")

        df = cls.read_excel_dataframe(file_bytes)
        total_rows = len(df)
        imported = 0
        skipped = 0
        error_details: List[RowErrorDetail] = []

        # Pre-fetch existing customer codes for this company to prevent duplicates
        existing_codes_query = select(Customer.customer_code).where(Customer.company_id == company_id)
        existing_codes = set(db.execute(existing_codes_query).scalars().all())

        seen_in_batch = set()

        for idx, row in df.iterrows():
            row_num = idx + 2  # Excel 1-based, plus header row
            row_dict = row.to_dict()

            # Extract fields via mapping
            code_col = mapping.get("customer_code")
            name_col = mapping.get("customer_name")
            email_col = mapping.get("email")
            phone_col = mapping.get("phone")
            active_col = mapping.get("active")

            code = _clean_val(row.get(code_col)) if code_col else None
            name = _clean_val(row.get(name_col)) if name_col else None
            email = _clean_val(row.get(email_col)) if email_col else None
            phone = _clean_val(row.get(phone_col)) if phone_col else None
            active = _clean_bool(row.get(active_col)) if active_col else True

            # Validation: Empty required fields
            if not code:
                error_details.append(RowErrorDetail(
                    row_number=row_num,
                    field="customer_code",
                    reason="Customer code is missing or empty",
                    raw_data=row_dict
                ))
                continue

            if not name:
                error_details.append(RowErrorDetail(
                    row_number=row_num,
                    field="customer_name",
                    reason="Customer name is missing or empty",
                    raw_data=row_dict
                ))
                continue

            # Validation: Duplicate in batch
            if code in seen_in_batch:
                error_details.append(RowErrorDetail(
                    row_number=row_num,
                    field="customer_code",
                    reason=f"Duplicate customer code '{code}' in upload sheet",
                    raw_data=row_dict
                ))
                continue

            # Validation: Duplicate in database for this company
            if code in existing_codes:
                error_details.append(RowErrorDetail(
                    row_number=row_num,
                    field="customer_code",
                    reason=f"Customer code '{code}' already exists for this company",
                    raw_data=row_dict
                ))
                continue

            # Valid customer, add to session
            customer = Customer(
                company_id=company_id,
                customer_code=code,
                customer_name=name,
                email=email,
                phone=phone,
                active=active
            )
            db.add(customer)
            seen_in_batch.add(code)
            existing_codes.add(code)
            imported += 1

        db.commit()

        return ImportSummaryResponse(
            entity_type="customers",
            total_rows=total_rows,
            imported=imported,
            skipped=skipped,
            errors=len(error_details),
            error_details=error_details
        )

    @classmethod
    def import_products(
        cls,
        db: Session,
        company_id: int,
        file_bytes: bytes,
        mapping: Dict[str, str]
    ) -> ImportSummaryResponse:
        """
        Imports products from Excel applying dynamic column mapping with row-level error reporting.
        """
        req_fields = REQUIRED_TARGET_FIELDS["products"]
        for rf in req_fields:
            if rf not in mapping or not mapping[rf]:
                raise ValueError(f"Missing required mapping for field: '{rf}'")

        df = cls.read_excel_dataframe(file_bytes)
        total_rows = len(df)
        imported = 0
        skipped = 0
        error_details: List[RowErrorDetail] = []

        # Pre-fetch existing product SKUs for this company
        existing_skus_query = select(Product.sku).where(Product.company_id == company_id)
        existing_skus = set(db.execute(existing_skus_query).scalars().all())
        existing_products = {p.sku: p for p in db.execute(select(Product).where(Product.company_id == company_id)).scalars()}

        seen_in_batch = set()

        for idx, row in df.iterrows():
            row_num = idx + 2
            row_dict = row.to_dict()

            sku_col = mapping.get("sku")
            desc_col = mapping.get("description")
            barcode_col = mapping.get("barcode")
            unit_col = mapping.get("unit")
            active_col = mapping.get("active")
            gross_col = mapping.get("kg_per_piece")

            sku = _clean_val(row.get(sku_col)) if sku_col else None
            description = _clean_val(row.get(desc_col)) if desc_col else None
            barcode = _clean_val(row.get(barcode_col)) if barcode_col else None
            unit = _clean_val(row.get(unit_col)) if unit_col else "piece"
            active = _clean_bool(row.get(active_col)) if active_col else True
            gross_raw = _clean_val(row.get(gross_col)) if gross_col else None
            try:
                gross_weight = Decimal(gross_raw.replace(",", ".")) if gross_raw is not None else None
            except InvalidOperation:
                gross_weight = None
            if gross_raw is not None and (gross_weight is None or not gross_weight.is_finite()
                                          or gross_weight < Decimal("0.000001") or gross_weight > 1_000_000):
                error_details.append(RowErrorDetail(row_number=row_num, field="kg_per_piece",
                    reason="Gross kilograms per piece must be positive and finite", raw_data=row_dict))
                continue

            # Validation: Missing required fields
            if not sku:
                error_details.append(RowErrorDetail(
                    row_number=row_num,
                    field="sku",
                    reason="Product SKU is missing or empty",
                    raw_data=row_dict
                ))
                continue

            if not description:
                error_details.append(RowErrorDetail(
                    row_number=row_num,
                    field="description",
                    reason="Product description is missing or empty",
                    raw_data=row_dict
                ))
                continue

            # Validation: Duplicate in batch
            if sku in seen_in_batch:
                error_details.append(RowErrorDetail(
                    row_number=row_num,
                    field="sku",
                    reason=f"Duplicate SKU '{sku}' in upload sheet",
                    raw_data=row_dict
                ))
                continue

            # Validation: Duplicate in database for this company
            if sku in existing_skus:
                if gross_col and gross_weight is not None:
                    existing = existing_products[sku]
                    if existing.kg_per_piece is None or existing.kg_per_piece != gross_weight:
                        existing.kg_per_piece = gross_weight
                        imported += 1
                    else:
                        skipped += 1
                    seen_in_batch.add(sku)
                    continue
                error_details.append(RowErrorDetail(
                    row_number=row_num,
                    field="sku",
                    reason=f"Product SKU '{sku}' already exists for this company",
                    raw_data=row_dict
                ))
                continue

            product = Product(
                company_id=company_id,
                sku=sku,
                description=description,
                barcode=barcode,
                unit=unit or "piece",
                kg_per_piece=gross_weight,
                active=active
            )
            db.add(product)
            seen_in_batch.add(sku)
            existing_skus.add(sku)
            imported += 1

        db.commit()

        return ImportSummaryResponse(
            entity_type="products",
            total_rows=total_rows,
            imported=imported,
            skipped=skipped,
            errors=len(error_details),
            error_details=error_details
        )

    @classmethod
    def import_packaging(
        cls,
        db: Session,
        company_id: int,
        file_bytes: bytes,
        mapping: Dict[str, str]
    ) -> ImportSummaryResponse:
        """
        Imports packaging configurations linked to existing company products.
        """
        req_fields = REQUIRED_TARGET_FIELDS["packaging"]
        for rf in req_fields:
            if rf not in mapping or not mapping[rf]:
                raise ValueError(f"Missing required mapping for field: '{rf}'")

        df = cls.read_excel_dataframe(file_bytes)
        total_rows = len(df)
        imported = 0
        skipped = 0
        error_details: List[RowErrorDetail] = []

        # Parse and validate spreadsheet values before reserving SQLite's
        # single writer. Only database-dependent checks happen under the lock.
        prepared_rows = []
        for idx, row in df.iterrows():
            row_num = idx + 2
            row_dict = row.to_dict()
            product_sku = _clean_val(row.get(mapping.get("product_sku")))
            package_type = _clean_val(row.get(mapping.get("package_type")))
            pieces_val = row.get(mapping.get("pieces_per_case"))
            pieces = _clean_float(pieces_val)
            weight = _clean_float(row.get(mapping.get("weight")))
            unit = _clean_val(row.get(mapping.get("unit"))) or "piece"
            package_code = _clean_val(row.get(mapping.get("package_code")))
            packaging_barcode = _clean_val(row.get(mapping.get("packaging_barcode")))

            if not product_sku:
                error_details.append(RowErrorDetail(
                    row_number=row_num, field="product_sku",
                    reason="Parent product SKU is missing or empty", raw_data=row_dict,
                ))
                continue
            if not package_type:
                error_details.append(RowErrorDetail(
                    row_number=row_num, field="package_type",
                    reason="Package type is missing or empty", raw_data=row_dict,
                ))
                continue
            if pieces is None or pieces <= 0:
                error_details.append(RowErrorDetail(
                    row_number=row_num, field="pieces_per_case",
                    reason=f"Invalid pieces_per_case value '{pieces_val}', must be a positive number",
                    raw_data=row_dict,
                ))
                continue
            prepared_rows.append((
                row_num, row_dict, product_sku, package_type, pieces,
                weight, unit, package_code, packaging_barcode,
            ))

        if not prepared_rows:
            return ImportSummaryResponse(
                entity_type="packaging", total_rows=total_rows,
                imported=0, skipped=0, errors=len(error_details),
                error_details=error_details,
            )

        # SQLite has one writer. Reserve it only after parsing, then perform the
        # lookup and inserts in the same transaction so concurrent imports see
        # the first writer's committed packaging rows.
        db.connection().exec_driver_sql("BEGIN IMMEDIATE")

        # Pre-fetch products and packaging definitions for this company.
        products_query = select(Product.id, Product.sku).where(Product.company_id == company_id)
        sku_to_product_id = {sku: pid for pid, sku in db.execute(products_query).all()}
        existing_packaging = db.execute(
            select(Packaging).where(Packaging.company_id == company_id)
        ).scalars().all()
        by_code: Dict[str, List[Packaging]] = {}
        by_barcode: Dict[str, List[Packaging]] = {}
        by_definition: Dict[tuple, List[Packaging]] = {}
        by_scope: Dict[tuple, List[Packaging]] = {}

        def definition(packaging: Packaging) -> tuple:
            return (
                packaging.product_id, packaging.package_type,
                packaging.pieces_per_case, packaging.weight, packaging.unit,
            )

        def index(packaging: Packaging) -> None:
            if packaging.package_code:
                by_code.setdefault(packaging.package_code, []).append(packaging)
            if packaging.packaging_barcode:
                by_barcode.setdefault(packaging.packaging_barcode, []).append(packaging)
            by_definition.setdefault(definition(packaging), []).append(packaging)
            by_scope.setdefault((packaging.product_id, packaging.package_type, packaging.unit), []).append(packaging)

        for packaging in existing_packaging:
            index(packaging)

        for (row_num, row_dict, product_sku, package_type, pieces,
             weight, unit, package_code, packaging_barcode) in prepared_rows:
            if product_sku not in sku_to_product_id:
                error_details.append(RowErrorDetail(
                    row_number=row_num,
                    field="product_sku",
                    reason=f"Product with SKU '{product_sku}' does not exist for this company",
                    raw_data=row_dict
                ))
                continue

            product_id = sku_to_product_id[product_sku]
            incoming_definition = (product_id, package_type, pieces, weight, unit)
            candidates = {
                id(packaging): packaging
                for packaging in (
                    by_code.get(package_code, []) if package_code else []
                ) + (
                    by_barcode.get(packaging_barcode, []) if packaging_barcode else []
                )
            }
            if len(candidates) > 1:
                error_details.append(RowErrorDetail(
                    row_number=row_num,
                    field="package_code",
                    reason="Package code and barcode identify different existing packaging rows",
                    raw_data=row_dict,
                ))
                continue
            if candidates:
                existing = next(iter(candidates.values()))
                if (definition(existing) == incoming_definition
                    and existing.package_code == package_code
                    and existing.packaging_barcode == packaging_barcode):
                    skipped += 1
                else:
                    error_details.append(RowErrorDetail(
                        row_number=row_num,
                        field="package_code",
                        reason="Existing package code or barcode has different values; review it before importing",
                        raw_data=row_dict,
                    ))
                continue
            if by_definition.get(incoming_definition):
                existing = by_definition[incoming_definition][0]
                if not package_code and not packaging_barcode and not existing.package_code and not existing.packaging_barcode:
                    skipped += 1
                else:
                    error_details.append(RowErrorDetail(
                        row_number=row_num,
                        field="package_code",
                        reason="This packaging definition already exists with different identifiers",
                        raw_data=row_dict,
                    ))
                continue
            if not package_code and not packaging_barcode and by_scope.get((product_id, package_type, unit)):
                error_details.append(RowErrorDetail(
                    row_number=row_num,
                    field="package_code",
                    reason="Packaging with this product, type and unit already exists with different values; add a stable code or barcode",
                    raw_data=row_dict,
                ))
                continue
            packaging = Packaging(
                company_id=company_id,
                product_id=product_id,
                package_code=package_code,
                packaging_barcode=packaging_barcode,
                package_type=package_type,
                pieces_per_case=pieces,
                weight=weight,
                unit=unit
            )
            db.add(packaging)
            index(packaging)
            imported += 1

        db.commit()

        error_details.sort(key=lambda detail: detail.row_number)
        return ImportSummaryResponse(
            entity_type="packaging",
            total_rows=total_rows,
            imported=imported,
            skipped=skipped,
            errors=len(error_details),
            error_details=error_details
        )
