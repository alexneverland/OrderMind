from typing import List, Optional, Dict, Tuple
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import select, or_
from rapidfuzz import fuzz

from backend.app.models.product import Product, ProductAlias, Packaging
from backend.app.models.memory import CustomerProductAlias
from backend.app.core.text_normalizer import normalize_text, normalize_unit, stem_phrase
from backend.app.schemas.matching import (
    MatchCandidateDto,
    MatchEvidence,
    ConfidenceResult,
    MatchedProductInfo,
    LineMatchResult,
    MatchDecision,
    MatchPriority
)
from backend.app.services.confidence_scorer import ConfidenceScorer
from backend.app.services.packaging_resolver import packaging_unit, resolve_product_packaging


EVIDENCE_TYPE_PRIORITY: Dict[str, MatchPriority] = {
    "exact_sku": MatchPriority.EXACT_SKU,
    "exact_barcode": MatchPriority.EXACT_BARCODE,
    "exact_packaging_code": MatchPriority.EXACT_PACKAGE_CODE,
    "exact_packaging_barcode": MatchPriority.EXACT_PACKAGE_BARCODE,
    "customer_alias_exact": MatchPriority.EXACT_CUSTOMER_ALIAS,
    "global_alias_exact": MatchPriority.EXACT_GLOBAL_ALIAS,
    "exact_normalized_description": MatchPriority.EXACT_NORMALIZED_DESCRIPTION,
    "fuzzy_customer_alias": MatchPriority.FUZZY_CUSTOMER_ALIAS,
    "fuzzy_alias": MatchPriority.FUZZY_GLOBAL_ALIAS,
    "fuzzy_description": MatchPriority.FUZZY_DESCRIPTION,
}



class MatchingEngine:
    """
    Deterministically matches parsed customer phrases against real business master data.
    Order of candidate search:
    1. Exact SKU
    2. Exact Barcode
    3. Customer-Specific Alias
    4. Global Product Alias
    5. Exact Normalized Description
    6. Fuzzy Description / Alias Matching via RapidFuzz
    """

    @classmethod
    def match_line(
        cls,
        db: Session,
        company_id: int,
        customer_id: int,
        line_number: int,
        original_text: str,
        product_phrase: str,
        quantity: float,
        unit: str,
        raw_unit: Optional[str] = None,
        unit_explicit: bool = False
    ) -> LineMatchResult:
        norm_phrase = normalize_text(product_phrase)
        raw_phrase = product_phrase.strip()
        stem_phrase_str = stem_phrase(norm_phrase)

        # Dictionary of product_id -> candidate data
        candidate_map: Dict[int, Dict] = {}

        # 1. Exact SKU Match (Company isolated)
        sku_stmt = (
            select(Product)
            .options(joinedload(Product.packagings))
            .where(
                Product.company_id == company_id,
                Product.active.is_(True),
                (Product.sku.ilike(raw_phrase)) | (Product.sku.ilike(norm_phrase))
            )
        )
        for prod in db.execute(sku_stmt).unique().scalars().all():
            cls._add_evidence(
                candidate_map, prod,
                evidence_type="exact_sku", score=1.0,
                detail=f"Exact match on product SKU '{prod.sku}'"
            )

        # 2. Exact Barcode Match
        if raw_phrase:
            barcode_stmt = (
                select(Product)
                .options(joinedload(Product.packagings))
                .where(
                    Product.company_id == company_id,
                    Product.active.is_(True),
                    Product.barcode == raw_phrase
                )
            )
            for prod in db.execute(barcode_stmt).unique().scalars().all():
                cls._add_evidence(
                    candidate_map, prod,
                    evidence_type="exact_barcode", score=1.0,
                    detail=f"Exact barcode match '{prod.barcode}'"
                )

            package_stmt = (
                select(Packaging, Product)
                .join(Product, Packaging.product_id == Product.id)
                .options(joinedload(Product.packagings))
                .where(
                    Product.company_id == company_id,
                    Product.active.is_(True),
                    (Packaging.package_code == raw_phrase) |
                    (Packaging.packaging_barcode == raw_phrase),
                )
            )
            for package, prod in db.execute(package_stmt).unique().all():
                cls._add_evidence(
                    candidate_map, prod,
                    evidence_type=("exact_packaging_code" if package.package_code == raw_phrase
                                   else "exact_packaging_barcode"),
                    score=1.0,
                    detail=f"Exact packaging identifier '{raw_phrase}'",
                )

        # 3. Customer-Specific Alias Match (Isolated to customer_id via index)
        if norm_phrase:
            cust_alias_filters = [CustomerProductAlias.normalized_phrase == norm_phrase]
            if stem_phrase_str and len(stem_phrase_str) >= 3:
                cust_alias_filters.append(CustomerProductAlias.normalized_phrase.like(f"{stem_phrase_str}%"))

            cust_alias_stmt = (
                select(CustomerProductAlias, Product)
                .join(Product, CustomerProductAlias.product_id == Product.id)
                .options(joinedload(Product.packagings))
                .where(
                    CustomerProductAlias.customer_id == customer_id,
                    CustomerProductAlias.active.is_(True),
                    Product.company_id == company_id,
                    Product.active.is_(True),
                    or_(*cust_alias_filters) if len(cust_alias_filters) > 1 else cust_alias_filters[0]
                )
            )
            cust_aliases_list = db.execute(cust_alias_stmt).unique().all()
            for alias_row, prod in cust_aliases_list:
                alias_norm = alias_row.normalized_phrase
                alias_stem = stem_phrase(alias_norm)
                if alias_norm == norm_phrase:
                    cls._add_evidence(
                        candidate_map, prod,
                        evidence_type="customer_alias_exact", score=1.0,
                        detail=f"Customer alias '{alias_row.original_phrase}' matched",
                        confirmed_count=alias_row.confirmed_count,
                        corrected_count=alias_row.corrected_count
                    )
                elif stem_phrase_str and alias_stem == stem_phrase_str:
                    cls._add_evidence(
                        candidate_map, prod,
                        evidence_type="customer_alias_exact", score=1.0,
                        detail=f"Customer alias '{alias_row.original_phrase}' matched (inflection variation)",
                        confirmed_count=alias_row.confirmed_count,
                        corrected_count=alias_row.corrected_count
                    )

        # 4. Global ProductAlias Match (Isolated to company_id via index)
        if norm_phrase:
            global_alias_filters = [ProductAlias.normalized_phrase == norm_phrase]
            if stem_phrase_str and len(stem_phrase_str) >= 3:
                global_alias_filters.append(ProductAlias.normalized_phrase.like(f"{stem_phrase_str}%"))

            global_alias_stmt = (
                select(ProductAlias, Product)
                .join(Product, ProductAlias.product_id == Product.id)
                .options(joinedload(Product.packagings))
                .where(
                    ProductAlias.company_id == company_id,
                    ProductAlias.active.is_(True),
                    Product.active.is_(True),
                    or_(*global_alias_filters) if len(global_alias_filters) > 1 else global_alias_filters[0]
                )
            )
            global_aliases_list = db.execute(global_alias_stmt).unique().all()

            for g_alias, prod in global_aliases_list:
                g_alias_norm = g_alias.normalized_phrase
                g_alias_stem = stem_phrase(g_alias_norm)
                if g_alias_norm == norm_phrase:
                    cls._add_evidence(
                        candidate_map, prod,
                        evidence_type="global_alias_exact", score=1.0,
                        detail=f"Global company alias '{g_alias.original_phrase}' matched"
                    )
                elif stem_phrase_str and g_alias_stem == stem_phrase_str:
                    cls._add_evidence(
                        candidate_map, prod,
                        evidence_type="global_alias_exact", score=1.0,
                        detail=f"Global company alias '{g_alias.original_phrase}' matched (inflection variation)"
                    )

        # 5. Exact Normalized Description Match
        exact_description_stmt = (
            select(Product)
            .options(joinedload(Product.packagings))
            .where(
                Product.company_id == company_id,
                Product.active.is_(True),
                or_(Product.normalized_description == norm_phrase,
                    Product.stemmed_description == stem_phrase_str),
            )
        )
        for prod in db.execute(exact_description_stmt).unique().scalars():
            if prod.normalized_description == norm_phrase:
                cls._add_evidence(
                    candidate_map, prod,
                    evidence_type="exact_normalized_description", score=1.0,
                    detail=f"Exact normalized match with product description '{prod.description}'"
                )
            elif stem_phrase_str and prod.stemmed_description == stem_phrase_str:
                cls._add_evidence(
                    candidate_map, prod,
                    evidence_type="exact_normalized_description", score=1.0,
                    detail=f"Exact normalized match with product description '{prod.description}' (inflection variation)"
                )

        # 6. Fuzzy Description / Alias Matching via RapidFuzz (Fallback if no exact match found)
        if not candidate_map and norm_phrase:
            # A bounded prefix range keeps one line from loading the full catalog.
            prefix = norm_phrase.split()[0][:3]
            if len(prefix) < 3:
                prefix = ""
            fuzzy_products_stmt = (
                select(Product)
                .options(joinedload(Product.packagings))
                .where(
                    Product.company_id == company_id,
                    Product.active.is_(True),
                    Product.normalized_description >= prefix,
                    Product.normalized_description < prefix + "\uffff",
                )
                .order_by(Product.normalized_description, Product.id)
                .limit(200)
            ) if prefix else None
            fuzzy_products = list(db.execute(fuzzy_products_stmt).unique().scalars()) if fuzzy_products_stmt is not None else []
            if not fuzzy_products and prefix:
                fuzzy_products = list(db.execute(
                    select(Product)
                    .options(joinedload(Product.packagings))
                    .where(
                        Product.company_id == company_id,
                        Product.active.is_(True),
                        Product.normalized_description.contains(prefix),
                    )
                    .order_by(Product.id)
                    .limit(200)
                ).unique().scalars())
            for prod in fuzzy_products:
                prod_norm_desc = prod.normalized_description
                token_ratio = fuzz.token_set_ratio(norm_phrase, prod_norm_desc)
                partial_ratio = fuzz.partial_ratio(norm_phrase, prod_norm_desc)
                best_fuzzy = max(token_ratio, partial_ratio * 0.92)
                if best_fuzzy >= 45:
                    cls._add_evidence(
                        candidate_map, prod,
                        evidence_type="fuzzy_description",
                        score=round(best_fuzzy / 100.0, 4),
                        detail=f"Fuzzy match similarity {int(best_fuzzy)}% with '{prod.description}'"
                    )

            # Also check aliases fuzzy if needed
            fuzzy_alias_stmt = (
                select(ProductAlias, Product)
                .join(Product, ProductAlias.product_id == Product.id)
                .options(joinedload(Product.packagings))
                .where(
                    ProductAlias.company_id == company_id,
                    ProductAlias.active.is_(True),
                    Product.active.is_(True),
                    ProductAlias.normalized_phrase >= prefix,
                    ProductAlias.normalized_phrase < prefix + "\uffff",
                )
                .order_by(ProductAlias.normalized_phrase, ProductAlias.id)
                .limit(200)
            )
            for g_alias, prod in (db.execute(fuzzy_alias_stmt).unique().all() if prefix else []):
                g_alias_norm = g_alias.normalized_phrase
                g_fuzzy = fuzz.token_set_ratio(norm_phrase, g_alias_norm)
                if g_fuzzy >= 50:
                    cls._add_evidence(
                        candidate_map, prod,
                        evidence_type="fuzzy_alias",
                        score=round(g_fuzzy / 100.0, 4),
                        detail=f"Fuzzy alias similarity {int(g_fuzzy)}% with '{g_alias.original_phrase}'"
                    )

        # 7. Packaging Compatibility Check & Confidence Calculation
        scored_candidates: List[Tuple[float, MatchCandidateDto, ConfidenceResult, Product]] = []

        is_unknown_unit = (unit == "unknown" and unit_explicit is True)

        for prod_id, c_data in candidate_map.items():
            prod: Product = c_data["product"]
            evidences: List[MatchEvidence] = c_data["evidences"]
            # Primary evidence is selected by deterministic priority first, then score
            primary_ev = min(evidences, key=lambda e: (e.priority, -e.score))
            cand_priority = min(e.priority for e in evidences)

            # Packaging check
            packaging_compatible: Optional[bool] = None
            if unit_explicit and not is_unknown_unit:
                packaging_compatible, _, _ = resolve_product_packaging(prod, unit)

            conf_res = ConfidenceScorer.calculate_confidence(
                primary_evidence_type=primary_ev.evidence_type,
                base_match_score=primary_ev.score,
                evidence_list=evidences,
                confirmed_count=c_data.get("confirmed_count", 0),
                corrected_count=c_data.get("corrected_count", 0),
                packaging_compatible=packaging_compatible,
                is_unknown_unit=is_unknown_unit,
                raw_unit=raw_unit
            )

            candidate_dto = MatchCandidateDto(
                product_id=prod.id,
                sku=prod.sku,
                description=prod.description,
                barcode=prod.barcode,
                score=conf_res.score,
                match_priority=cand_priority,
                evidence=evidences
            )
            scored_candidates.append((conf_res.score, candidate_dto, conf_res, prod))

        # Sort candidates deterministically:
        # 1. Match Priority ASCENDING (1=SKU, 2=Barcode, 3=Cust Alias, 4=Global Alias, 5=Description, etc.)
        # 2. Confidence Score DESCENDING (-score)
        scored_candidates.sort(key=lambda x: (x[1].match_priority, -x[0]))

        if not scored_candidates:
            # Unresolved match
            return LineMatchResult(
                line_number=line_number,
                original_text=original_text,
                product_phrase=product_phrase,
                quantity=quantity,
                unit=unit,
                raw_unit=raw_unit,
                unit_explicit=unit_explicit,
                best_match=None,
                confidence=ConfidenceResult(
                    score=0.0,
                    decision=MatchDecision.UNRESOLVED,
                    reasons=["No matching products found in catalog"]
                ),
                alternatives=[]
            )

        # Ambiguity check between strong candidates
        if len(scored_candidates) > 1:
            best_score, best_cand_dto, best_conf, best_prod = scored_candidates[0]
            second_score, second_cand_dto, second_conf, second_prod = scored_candidates[1]
            best_conf = ConfidenceScorer.check_ambiguity(
                best_cand=best_cand_dto,
                best_conf=best_conf,
                second_cand=second_cand_dto,
                second_conf=second_conf
            )
            scored_candidates[0] = (best_score, best_cand_dto, best_conf, best_prod)

        # Best candidate
        best_score, best_cand_dto, best_conf, best_prod = scored_candidates[0]
        best_cand_dto.rank = 1

        packaging_identifier = raw_phrase if any(
            ev.evidence_type in ("exact_packaging_code", "exact_packaging_barcode")
            for ev in best_cand_dto.evidence
        ) else None
        final_unit = unit if unit_explicit else best_prod.unit
        matched_packaging_id = None
        if packaging_identifier:
            matching_package = [p for p in best_prod.packagings
                                if raw_phrase in (p.package_code, p.packaging_barcode)]
            if len(matching_package) == 1 and not unit_explicit:
                final_unit = packaging_unit(matching_package[0].package_type)
                if final_unit == "unknown":
                    final_unit = normalize_unit(matching_package[0].unit)
        if unit_explicit or packaging_identifier:
            compatible, matched_packaging_id, reason = resolve_product_packaging(
                best_prod, final_unit, packaging_identifier
            )
            if not compatible:
                best_conf.decision = MatchDecision.NEEDS_REVIEW
                best_conf.reasons.append(f"Packaging requires review: {reason}")

        best_match_info = MatchedProductInfo(
            product_id=best_prod.id,
            sku=best_prod.sku,
            description=best_prod.description,
            barcode=best_prod.barcode,
            unit=best_prod.unit
        )

        # Alternatives (rank 2 to 5)
        alternatives: List[MatchCandidateDto] = []
        for rank_idx, (_, alt_dto, _, _) in enumerate(scored_candidates[1:5], start=2):
            alt_dto.rank = rank_idx
            alternatives.append(alt_dto)

        return LineMatchResult(
            line_number=line_number,
            original_text=original_text,
            product_phrase=product_phrase,
            quantity=quantity,
            unit=unit,
            raw_unit=raw_unit,
            unit_explicit=unit_explicit,
            best_match=best_match_info,
            matched_packaging_id=matched_packaging_id,
            final_unit=final_unit,
            confidence=best_conf,
            alternatives=alternatives
        )

    @staticmethod
    def _add_evidence(
        candidate_map: Dict[int, Dict],
        prod: Product,
        evidence_type: str,
        score: float,
        detail: str,
        confirmed_count: int = 0,
        corrected_count: int = 0
    ) -> None:
        priority = EVIDENCE_TYPE_PRIORITY.get(evidence_type, MatchPriority.UNKNOWN)
        ev = MatchEvidence(evidence_type=evidence_type, score=score, detail=detail, priority=priority)
        if prod.id not in candidate_map:
            candidate_map[prod.id] = {
                "product": prod,
                "evidences": [ev],
                "confirmed_count": confirmed_count,
                "corrected_count": corrected_count
            }
        else:
            candidate_map[prod.id]["evidences"].append(ev)
            if confirmed_count > candidate_map[prod.id]["confirmed_count"]:
                candidate_map[prod.id]["confirmed_count"] = confirmed_count
            if corrected_count > candidate_map[prod.id]["corrected_count"]:
                candidate_map[prod.id]["corrected_count"] = corrected_count
