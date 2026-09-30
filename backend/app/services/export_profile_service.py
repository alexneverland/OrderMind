from typing import List, Optional
from sqlalchemy.orm import Session
from sqlalchemy import select

from backend.app.models.export import ExportProfile, ExportFieldMapping
from backend.app.models.company import Company
from backend.app.models.product import Product
from backend.app.schemas.pallet import PalletConfig
from backend.app.schemas.export import (
    ExportProfileCreate,
    ExportProfileUpdate,
    ExportFormat,
    MappingType,
)
from backend.app.services.export_registry import AVAILABLE_SOURCE_FIELDS


class ExportProfileValidationError(ValueError):
    pass


class ExportProfileService:
    """
    Manages CRUD and validation for user-configurable ERP/warehouse export profiles.
    """

    SUPPORTED_FORMATS = {"excel", "xlsx", "csv", "json", "order_sheet"}
    SUPPORTED_DELIMITERS = {",", ";", "\t", "|"}
    SUPPORTED_ENCODINGS = {"utf-8", "utf-8-sig", "windows-1253", "iso-8859-7", "latin1", "ascii"}

    @staticmethod
    def validate_palletization(db: Session, company_id: int, fmt: str, config: PalletConfig) -> None:
        if config.enabled and fmt != "order_sheet":
            raise ExportProfileValidationError("Pallet planning requires order_sheet format")
        ids = {pid for group in config.dedicated_groups for pid in group.product_ids}
        if ids:
            found = set(db.execute(select(Product.id).where(Product.company_id == company_id,
                Product.active.is_(True), Product.id.in_(ids))).scalars())
            if found != ids:
                raise ExportProfileValidationError("Dedicated pallet products must belong to this company")

    @classmethod
    def validate_order_sheet_policy(cls, fmt, separate, marker, output_unit, convert):
        if fmt != "order_sheet":
            if separate or marker or output_unit != "source" or convert:
                raise ExportProfileValidationError("Bonus and conversion rules require order_sheet format")
            return
        if output_unit not in {"source", "piece"}:
            raise ExportProfileValidationError("Order sheet output unit must be source or piece")
        if convert != (output_unit == "piece"):
            raise ExportProfileValidationError("Case conversion must match piece output unit")
        if marker and not separate:
            raise ExportProfileValidationError("Bonus marker requires a separate bonus row")
        if separate and (not marker or not marker.strip()):
            raise ExportProfileValidationError("Separate bonus rows require a marker")

    @classmethod
    def validate_profile_mappings(cls, mappings) -> None:
        if not mappings or len(mappings) == 0:
            raise ExportProfileValidationError("Export profile must define at least one column mapping.")

        seen_orders = set()
        seen_col_names = set()
        for idx, m in enumerate(mappings):
            if not m.output_column_name or not m.output_column_name.strip():
                raise ExportProfileValidationError(f"Mapping #{idx+1} has an empty output column name.")

            col_name_norm = m.output_column_name.strip().lower()
            if col_name_norm in seen_col_names:
                raise ExportProfileValidationError(f"Duplicate output_column_name '{m.output_column_name.strip()}' in export profile.")
            seen_col_names.add(col_name_norm)

            if m.column_order in seen_orders:
                raise ExportProfileValidationError(f"Duplicate column_order '{m.column_order}' in export profile.")
            seen_orders.add(m.column_order)

            m_type = m.mapping_type.value if hasattr(m.mapping_type, "value") else str(m.mapping_type)
            if m_type == MappingType.SOURCE_FIELD.value:
                if not m.source_field:
                    raise ExportProfileValidationError(
                        f"Column '{m.output_column_name}' has type 'source_field' but no source_field specified."
                    )
                if m.source_field not in AVAILABLE_SOURCE_FIELDS:
                    raise ExportProfileValidationError(
                        f"Invalid source_field '{m.source_field}'. Whitelisted fields: {list(AVAILABLE_SOURCE_FIELDS.keys())}"
                    )
            elif m_type == MappingType.CONSTANT.value:
                if m.constant_value is None:
                    raise ExportProfileValidationError(
                        f"Column '{m.output_column_name}' has type 'constant' but no constant_value specified."
                    )

    @classmethod
    def create_profile(cls, db: Session, payload: ExportProfileCreate) -> ExportProfile:
        company = db.get(Company, payload.company_id)
        if not company:
            raise ValueError(f"Company with id {payload.company_id} does not exist")

        fmt = payload.format.lower().strip()
        if fmt not in cls.SUPPORTED_FORMATS:
            raise ExportProfileValidationError(f"Unsupported format '{payload.format}'. Supported: {cls.SUPPORTED_FORMATS}")

        if fmt == "csv" and payload.delimiter not in cls.SUPPORTED_DELIMITERS:
            raise ExportProfileValidationError(f"Unsupported CSV delimiter '{payload.delimiter}'. Supported: {cls.SUPPORTED_DELIMITERS}")

        enc = (payload.encoding or "utf-8-sig").lower().strip()
        if enc not in cls.SUPPORTED_ENCODINGS:
            raise ExportProfileValidationError(f"Unsupported encoding '{payload.encoding}'. Supported: {sorted(list(cls.SUPPORTED_ENCODINGS))}")

        if fmt == "order_sheet":
            if payload.mappings:
                raise ExportProfileValidationError("Order sheet profiles have fixed columns and no mappings")
        else:
            cls.validate_profile_mappings(payload.mappings)
        cls.validate_order_sheet_policy(fmt, payload.bonus_separate_row, payload.bonus_marker,
                                        payload.quantity_output_unit, payload.convert_case_using_pieces_per_case)
        cls.validate_palletization(db, payload.company_id, fmt, payload.palletization)

        profile = ExportProfile(
            company_id=payload.company_id,
            name=payload.name.strip(),
            format=fmt,
            delimiter=payload.delimiter,
            include_header=payload.include_header,
            encoding=enc,
            bonus_separate_row=payload.bonus_separate_row,
            bonus_marker=payload.bonus_marker,
            quantity_output_unit=payload.quantity_output_unit,
            convert_case_using_pieces_per_case=payload.convert_case_using_pieces_per_case,
            palletization=payload.palletization.model_dump(mode="json"),
        )
        db.add(profile)
        db.flush()

        for m in sorted(payload.mappings, key=lambda x: x.column_order):
            m_type = m.mapping_type.value if hasattr(m.mapping_type, "value") else str(m.mapping_type)
            field_map = ExportFieldMapping(
                export_profile_id=profile.id,
                column_order=m.column_order,
                output_column_name=m.output_column_name.strip(),
                mapping_type=m_type,
                source_field=m.source_field.strip() if m.source_field else None,
                constant_value=m.constant_value if m.constant_value is not None else None
            )
            db.add(field_map)

        db.commit()
        db.refresh(profile)
        return profile

    @classmethod
    def get_profile(cls, db: Session, profile_id: int) -> Optional[ExportProfile]:
        return db.get(ExportProfile, profile_id)

    @classmethod
    def list_profiles(cls, db: Session, company_id: Optional[int] = None) -> List[ExportProfile]:
        stmt = select(ExportProfile)
        if company_id is not None:
            stmt = stmt.where(ExportProfile.company_id == company_id)
        stmt = stmt.order_by(ExportProfile.name)
        return list(db.execute(stmt).scalars().all())

    @classmethod
    def update_profile(cls, db: Session, profile_id: int, payload: ExportProfileUpdate) -> ExportProfile:
        profile = db.get(ExportProfile, profile_id)
        if not profile:
            raise ValueError(f"Export profile with id {profile_id} does not exist")

        if payload.name is not None:
            profile.name = payload.name.strip()

        if payload.format is not None:
            fmt = payload.format.lower().strip()
            if fmt not in cls.SUPPORTED_FORMATS:
                raise ExportProfileValidationError(f"Unsupported format '{payload.format}'.")
            if fmt != profile.format and "order_sheet" in {fmt, profile.format}:
                raise ExportProfileValidationError("Create a separate profile for the fixed order sheet format")
            profile.format = fmt

        if payload.delimiter is not None:
            if payload.delimiter not in cls.SUPPORTED_DELIMITERS:
                raise ExportProfileValidationError(f"Unsupported CSV delimiter '{payload.delimiter}'.")
            profile.delimiter = payload.delimiter

        if payload.include_header is not None:
            profile.include_header = payload.include_header

        if payload.encoding is not None:
            enc = payload.encoding.lower().strip()
            if enc not in cls.SUPPORTED_ENCODINGS:
                raise ExportProfileValidationError(f"Unsupported encoding '{payload.encoding}'. Supported: {sorted(list(cls.SUPPORTED_ENCODINGS))}")
            profile.encoding = enc

        for field in ("bonus_separate_row", "bonus_marker", "quantity_output_unit", "convert_case_using_pieces_per_case"):
            if field in payload.model_fields_set:
                value = getattr(payload, field)
                if value is None and field != "bonus_marker":
                    raise ExportProfileValidationError(f"{field} cannot be null")
                setattr(profile, field, value)

        if "palletization" in payload.model_fields_set:
            if payload.palletization is None:
                raise ExportProfileValidationError("palletization cannot be null")
            profile.palletization = payload.palletization.model_dump(mode="json")

        if payload.mappings is not None:
            if profile.format == "order_sheet":
                if payload.mappings:
                    raise ExportProfileValidationError("Order sheet profiles have fixed columns and no mappings")
            else:
                cls.validate_profile_mappings(payload.mappings)
            # Remove old mappings
            for m in list(profile.field_mappings):
                db.delete(m)
            db.flush()

            # Add new mappings
            for m in sorted(payload.mappings, key=lambda x: x.column_order):
                m_type = m.mapping_type.value if hasattr(m.mapping_type, "value") else str(m.mapping_type)
                field_map = ExportFieldMapping(
                    export_profile_id=profile.id,
                    column_order=m.column_order,
                    output_column_name=m.output_column_name.strip(),
                    mapping_type=m_type,
                    source_field=m.source_field.strip() if m.source_field else None,
                    constant_value=m.constant_value if m.constant_value is not None else None
                )
                db.add(field_map)

        if profile.format != "order_sheet" and not profile.field_mappings:
            raise ExportProfileValidationError("Export profile must define at least one column mapping")
        if profile.format == "csv":
            profile.delimiter = profile.delimiter or ","
            if profile.delimiter not in cls.SUPPORTED_DELIMITERS:
                raise ExportProfileValidationError("CSV profile requires a supported single-character delimiter")
        cls.validate_order_sheet_policy(profile.format, profile.bonus_separate_row, profile.bonus_marker,
                                        profile.quantity_output_unit, profile.convert_case_using_pieces_per_case)
        cls.validate_palletization(db, profile.company_id, profile.format, PalletConfig.model_validate(profile.palletization))

        db.commit()
        db.refresh(profile)
        return profile

    @classmethod
    def delete_profile(cls, db: Session, profile_id: int) -> bool:
        profile = db.get(ExportProfile, profile_id)
        if not profile:
            return False
        db.delete(profile)
        db.commit()
        return True
