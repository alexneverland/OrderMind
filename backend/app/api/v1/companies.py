from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from typing import List
from pydantic import ValidationError

from backend.app.core.database import get_db
from backend.app.models.company import Company
from backend.app.models.business_settings import CompanyBusinessSettings, CompanyRule
from backend.app.models.product import Product
from backend.app.models.customer import Customer
from backend.app.models.export import ExportProfile
from backend.app.schemas.business_settings import BusinessSettingsValues, BusinessSettingsResponse
from backend.app.services.business_settings_service import effective_business_settings
from backend.app.schemas.company import CompanyCreate, CompanyResponse
from backend.app.schemas.rules import (AnalyzeRequest, ApplyProposalRequest, ExportPatch, QuantityBonusConfig,
    ResolvedQuantityRule, RuleCandidate, RuleResponse, RuleUpdate, RuleWrite,
    RulesProposal, merged_settings)
from backend.app.services.company_rule_service import create_rule, rule_fingerprint, rule_response, validate_rule_scope
from backend.app.services.export_profile_service import ExportProfileService
from backend.app.services.rules_assistant import analyze_rule_description

router = APIRouter(prefix="/companies", tags=["Companies"])


@router.post("", response_model=CompanyResponse, status_code=status.HTTP_201_CREATED)
def create_company(payload: CompanyCreate, db: Session = Depends(get_db)):
    """Create a new tenant / business company."""
    company = Company(
        name=payload.name.strip(),
        tax_id=payload.tax_id.strip() if payload.tax_id else None
    )
    db.add(company)
    db.commit()
    db.refresh(company)
    return company


@router.get("", response_model=List[CompanyResponse])
def list_companies(db: Session = Depends(get_db)):
    """List all companies."""
    stmt = select(Company).order_by(Company.created_at.desc())
    return db.execute(stmt).scalars().all()


@router.get("/{company_id}", response_model=CompanyResponse)
def get_company(company_id: int, db: Session = Depends(get_db)):
    """Retrieve details for a specific company."""
    company = db.get(Company, company_id)
    if not company:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Company with id {company_id} not found"
        )
    return company


@router.get("/{company_id}/business-settings", response_model=BusinessSettingsResponse)
def get_business_settings(company_id: int, db: Session = Depends(get_db)):
    if not db.get(Company, company_id):
        raise HTTPException(status_code=404, detail="Company not found")
    return effective_business_settings(db, company_id)


@router.put("/{company_id}/business-settings", response_model=BusinessSettingsResponse)
def put_business_settings(company_id: int, payload: BusinessSettingsValues, db: Session = Depends(get_db)):
    if not db.get(Company, company_id):
        raise HTTPException(status_code=404, detail="Company not found")
    row = db.get(CompanyBusinessSettings, company_id)
    if row is None:
        row = CompanyBusinessSettings(company_id=company_id)
        db.add(row)
    for key, value in payload.model_dump().items():
        setattr(row, key, value)
    db.commit()
    db.refresh(row)
    return row


def _company_or_404(db: Session, company_id: int) -> None:
    if db.get(Company, company_id) is None:
        raise HTTPException(status_code=404, detail="Company not found")


def _resolve_reference(reference: str | None, records, key, label) -> tuple[int | None, list[RuleCandidate]]:
    if not reference:
        return None, []
    value = reference.strip().casefold()
    exact = [row for row in records if key(row).casefold() == value or label(row).casefold() == value]
    choices = exact or [row for row in records if value in key(row).casefold() or value in label(row).casefold()]
    candidates = [RuleCandidate(id=row.id, label=f"{key(row)} · {label(row)}") for row in choices[:20]]
    return (choices[0].id if len(choices) == 1 else None), candidates


@router.get("/{company_id}/rules", response_model=list[RuleResponse])
def list_company_rules(company_id: int, db: Session = Depends(get_db)):
    _company_or_404(db, company_id)
    rows = db.execute(select(CompanyRule).where(CompanyRule.company_id == company_id).order_by(CompanyRule.id)).scalars()
    return [rule_response(row) for row in rows]


@router.post("/{company_id}/rules", response_model=RuleResponse, status_code=201)
def post_company_rule(company_id: int, payload: RuleWrite, db: Session = Depends(get_db)):
    _company_or_404(db, company_id)
    try:
        row = create_rule(db, company_id, payload)
        db.commit()
        return rule_response(row)
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="Rule changed concurrently; reload and retry") from exc


@router.post("/{company_id}/rules/analyze", response_model=RulesProposal)
async def analyze_company_rules(company_id: int, payload: AnalyzeRequest, db: Session = Depends(get_db)):
    _company_or_404(db, company_id)
    db.rollback()  # Do not hold a DB transaction open during the AI request.
    try:
        analysis = await analyze_rule_description(payload.description)
    except (ValueError, ValidationError) as exc:
        raise HTTPException(status_code=422, detail="AI returned an invalid rules proposal") from exc
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Configured AI provider could not analyze the rules") from exc
    products = db.execute(select(Product).where(Product.company_id == company_id, Product.active.is_(True))).scalars().all()
    customers = db.execute(select(Customer).where(Customer.company_id == company_id, Customer.active.is_(True))).scalars().all()
    quantity_rules = []
    for draft in analysis.quantity_rules:
        product_id, product_candidates = _resolve_reference(draft.product_reference, products, lambda row: row.sku, lambda row: row.description)
        customer_id, customer_candidates = _resolve_reference(draft.customer_reference, customers, lambda row: row.customer_code, lambda row: row.customer_name)
        quantity_rules.append(ResolvedQuantityRule(
            **draft.model_dump(), product_id=product_id, customer_id=customer_id,
            product_candidates=product_candidates, customer_candidates=customer_candidates,
        ))
    profiles = db.execute(select(ExportProfile).where(
        ExportProfile.company_id == company_id, ExportProfile.format == "order_sheet"
    )).scalars().all()
    export_patch = analysis.export_patch.model_copy(update={"profile_id": profiles[0].id if len(profiles) == 1 else None}) if analysis.export_patch else None
    return RulesProposal(
        settings_patch=analysis.settings_patch, quantity_rules=quantity_rules,
        export_patch=export_patch,
        export_profile_candidates=[RuleCandidate(id=row.id, label=row.name) for row in profiles] if export_patch else [],
        unsupported_rules=analysis.unsupported_rules,
    )


@router.post("/{company_id}/rules/apply-proposal")
def apply_company_rules(company_id: int, payload: ApplyProposalRequest, db: Session = Depends(get_db)):
    _company_or_404(db, company_id)
    proposal = payload.proposal
    if not proposal.settings_patch.model_dump(exclude_none=True) and not proposal.quantity_rules and proposal.export_patch is None:
        raise HTTPException(status_code=400, detail="Proposal has no supported changes")
    try:
        current = effective_business_settings(db, company_id)
        values = merged_settings(current, proposal.settings_patch)
        settings_row = db.get(CompanyBusinessSettings, company_id)
        if settings_row is None:
            settings_row = CompanyBusinessSettings(company_id=company_id)
            db.add(settings_row)
        for key, value in values.model_dump().items():
            setattr(settings_row, key, value)
        created = []
        for item in proposal.quantity_rules:
            if item.product_reference and item.product_id is None:
                raise ValueError(f"Select a product for '{item.product_reference}'")
            if item.customer_reference and item.customer_id is None:
                raise ValueError(f"Select a customer for '{item.customer_reference}'")
            created.append(create_rule(db, company_id, RuleWrite(
                product_id=item.product_id, customer_id=item.customer_id,
                configuration=item.configuration,
            )))
        if proposal.export_patch is not None:
            patch: ExportPatch = proposal.export_patch
            if patch.profile_id is None:
                raise ValueError("Select an order-sheet export profile")
            profile = db.get(ExportProfile, patch.profile_id)
            if not profile or profile.company_id != company_id or profile.format != "order_sheet":
                raise ValueError("Export profile must be an order sheet in this company")
            for key, value in patch.model_dump(exclude_none=True, exclude={"profile_id"}).items():
                setattr(profile, key, value)
            ExportProfileService.validate_order_sheet_policy(
                profile.format, profile.bonus_separate_row, profile.bonus_marker,
                profile.quantity_output_unit, profile.convert_case_using_pieces_per_case,
            )
        db.commit()
        return {"settings": BusinessSettingsResponse.model_validate(settings_row),
                "rules": [rule_response(rule) for rule in created]}
    except (ValueError, ValidationError) as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="Rules changed concurrently; reload and retry") from exc


@router.put("/{company_id}/rules/{rule_id}", response_model=RuleResponse)
def put_company_rule(company_id: int, rule_id: int, payload: RuleUpdate, db: Session = Depends(get_db)):
    _company_or_404(db, company_id)
    rule = db.get(CompanyRule, rule_id)
    if not rule or rule.company_id != company_id:
        raise HTTPException(status_code=404, detail="Rule not found")
    try:
        product_id = payload.product_id if "product_id" in payload.model_fields_set else rule.product_id
        customer_id = payload.customer_id if "customer_id" in payload.model_fields_set else rule.customer_id
        validate_rule_scope(db, company_id, product_id, customer_id)
        rule.product_id = product_id
        rule.customer_id = customer_id
        if "configuration" in payload.model_fields_set:
            if payload.configuration is None:
                raise ValueError("configuration cannot be null")
            rule.configuration = payload.configuration.model_dump(mode="json")
        rule.fingerprint = rule_fingerprint(product_id, customer_id, QuantityBonusConfig.model_validate(rule.configuration))
        if payload.enabled is not None:
            rule.enabled = payload.enabled
        db.commit()
        return rule_response(rule)
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="An identical rule already exists") from exc


@router.delete("/{company_id}/rules/{rule_id}", status_code=204)
def disable_company_rule(company_id: int, rule_id: int, db: Session = Depends(get_db)):
    _company_or_404(db, company_id)
    rule = db.get(CompanyRule, rule_id)
    if not rule or rule.company_id != company_id:
        raise HTTPException(status_code=404, detail="Rule not found")
    rule.enabled = False
    db.commit()
