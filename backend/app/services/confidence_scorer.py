from typing import List, Optional, Dict, Any
from backend.app.schemas.matching import (
    ConfidenceResult,
    MatchDecision,
    MatchEvidence,
    MatchCandidateDto,
    MatchPriority
)


# Centralized Scoring Constants & Decision Thresholds
AUTO_ACCEPT_THRESHOLD = 0.95
NEEDS_REVIEW_THRESHOLD = 0.70
AMBIGUITY_SCORE_MARGIN = 0.05


# Base match weights (derived from strongest primary candidate evidence)
BASE_WEIGHT_EXACT_SKU = 0.98
BASE_WEIGHT_EXACT_BARCODE = 0.98
BASE_WEIGHT_EXACT_DESCRIPTION = 0.96
BASE_WEIGHT_GLOBAL_ALIAS_EXACT = 0.92
BASE_WEIGHT_CUSTOMER_ALIAS_EXACT = 0.90

# Modifiers & Adjustments
CONFIRMATION_BONUS_PER_HIT = 0.01
MAX_CONFIRMATION_BONUS = 0.08

CORRECTION_PENALTY_PER_HIT = 0.05
MAX_CORRECTION_PENALTY = 0.20

BONUS_PACKAGING_COMPATIBLE = 0.03
PENALTY_PACKAGING_INCOMPATIBLE = 0.15
PENALTY_UNKNOWN_EXPLICIT_UNIT = 0.20


class ConfidenceScorer:
    """
    Explainable, rule-based weighted confidence scorer.
    Calculates numerical score and generates detailed human-readable reasons.
    """

    @staticmethod
    def calculate_confidence(
        primary_evidence_type: str,
        base_match_score: float,
        evidence_list: List[MatchEvidence],
        confirmed_count: int = 0,
        corrected_count: int = 0,
        packaging_compatible: Optional[bool] = None,
        is_unknown_unit: bool = False,
        raw_unit: Optional[str] = None
    ) -> ConfidenceResult:
        reasons: List[str] = []
        score = 0.0

        primary_detail = ""
        for ev in evidence_list:
            if ev.evidence_type == primary_evidence_type:
                primary_detail = ev.detail
                break

        # 1. Base Score from primary match evidence
        if primary_evidence_type == "exact_sku":
            score = BASE_WEIGHT_EXACT_SKU
            reasons.append("+ Exact SKU match")
        elif primary_evidence_type in ("exact_barcode", "exact_packaging_code", "exact_packaging_barcode"):
            score = BASE_WEIGHT_EXACT_BARCODE
            reasons.append("+ Exact Barcode match" if primary_evidence_type == "exact_barcode"
                           else "+ Exact packaging identifier match")
        elif primary_evidence_type == "exact_normalized_description":
            score = BASE_WEIGHT_EXACT_DESCRIPTION
            reasons.append("+ Exact product description match")
        elif primary_evidence_type == "customer_alias_exact":
            score = BASE_WEIGHT_CUSTOMER_ALIAS_EXACT
            reasons.append(f"+ Customer-specific alias match: {primary_detail}" if primary_detail else "+ Customer-specific alias match")
        elif primary_evidence_type == "global_alias_exact":
            score = BASE_WEIGHT_GLOBAL_ALIAS_EXACT
            reasons.append(f"+ Global product alias match: {primary_detail}" if primary_detail else "+ Global product alias match")

        elif primary_evidence_type == "fuzzy_description":
            # Scale fuzzy score by 0.85
            score = round(base_match_score * 0.85, 4)
            reasons.append(f"+ Fuzzy description match ({int(base_match_score * 100)}% similarity)")
        elif primary_evidence_type == "fuzzy_alias":
            score = round(base_match_score * 0.80, 4)
            reasons.append(f"+ Fuzzy alias match ({int(base_match_score * 100)}% similarity)")
        else:
            score = round(base_match_score * 0.70, 4)
            reasons.append(f"Primary match: {primary_evidence_type}")

        # 2. Customer Confirmation History Bonus
        if confirmed_count > 0:
            # First confirmation is baseline, subsequent confirmations add bonus up to +0.08
            conf_bonus = min(MAX_CONFIRMATION_BONUS, (confirmed_count - 1) * CONFIRMATION_BONUS_PER_HIT)
            if conf_bonus > 0:
                score += conf_bonus
            reasons.append(f"+ Confirmed {confirmed_count} previous time{'s' if confirmed_count > 1 else ''}")

        # 3. Correction Penalty
        if corrected_count > 0:
            corr_penalty = min(MAX_CORRECTION_PENALTY, corrected_count * CORRECTION_PENALTY_PER_HIT)
            score -= corr_penalty
            reasons.append(f"- Past operator corrections on this alias ({corrected_count} times, -{int(corr_penalty * 100)}%)")

        # 4. Packaging Compatibility
        if packaging_compatible is True:
            score += BONUS_PACKAGING_COMPATIBLE
            reasons.append("+ Requested packaging/unit compatible with product")
        elif packaging_compatible is False:
            score -= PENALTY_PACKAGING_INCOMPATIBLE
            reasons.append(f"- Requested unit is incompatible with product packaging (-{int(PENALTY_PACKAGING_INCOMPATIBLE * 100)}%)")

        # 5. Unknown Explicit Unit Penalty (Crucial hardening: prevents auto-accept for unknown containers)
        if is_unknown_unit:
            score -= PENALTY_UNKNOWN_EXPLICIT_UNIT
            unit_display = f"'{raw_unit}'" if raw_unit else "unknown"
            reasons.append(f"- Unknown explicit unit {unit_display} requested (-{int(PENALTY_UNKNOWN_EXPLICIT_UNIT * 100)}%)")

        # Normalize score bounds
        final_score = max(0.0, min(1.0, round(score, 2)))

        # 6. Centralized Decision Determination
        # Safety rule: If explicit unknown unit was requested, it CANNOT be auto_accepted
        if is_unknown_unit and final_score >= AUTO_ACCEPT_THRESHOLD:
            decision = MatchDecision.NEEDS_REVIEW
            reasons.append("! Downgraded from auto_accept to needs_review due to unknown explicit unit")
        elif final_score >= AUTO_ACCEPT_THRESHOLD:
            decision = MatchDecision.AUTO_ACCEPT
        elif final_score >= NEEDS_REVIEW_THRESHOLD:
            decision = MatchDecision.NEEDS_REVIEW
        else:
            decision = MatchDecision.UNRESOLVED

        return ConfidenceResult(
            score=final_score,
            decision=decision,
            reasons=reasons
        )

    @staticmethod
    def check_ambiguity(
        best_cand: MatchCandidateDto,
        best_conf: ConfidenceResult,
        second_cand: Optional[MatchCandidateDto] = None,
        second_conf: Optional[ConfidenceResult] = None,
        ambiguity_margin: float = AMBIGUITY_SCORE_MARGIN,
    ) -> ConfidenceResult:
        """
        Ambiguity protection between strong candidates:
        - If two or more distinct products have very close scores (score gap <= margin)
          and both are above meaningful confidence (NEEDS_REVIEW_THRESHOLD).
        - Or if duplicate deterministic evidence exists (same high-tier priority <= EXACT_NORMALIZED_DESCRIPTION).
        Then auto_accept is downgraded to needs_review with explainable reason.
        """
        if not second_cand or not second_conf:
            return best_conf

        if best_cand.product_id == second_cand.product_id:
            return best_conf

        # 1. Deterministic duplicate evidence check
        is_deterministic_duplicate = (
            best_cand.match_priority == second_cand.match_priority
            and best_cand.match_priority <= MatchPriority.EXACT_NORMALIZED_DESCRIPTION
        )

        # 2. Score gap check between strong candidates
        is_score_gap_ambiguous = (
            best_conf.score >= NEEDS_REVIEW_THRESHOLD
            and second_conf.score >= NEEDS_REVIEW_THRESHOLD
            and abs(best_conf.score - second_conf.score) <= ambiguity_margin
        )

        if is_deterministic_duplicate or is_score_gap_ambiguous:
            if best_conf.decision == MatchDecision.AUTO_ACCEPT:
                best_conf.decision = MatchDecision.NEEDS_REVIEW

            ambiguity_reason = "Multiple strong product candidates detected; manual review required."
            if ambiguity_reason not in best_conf.reasons:
                best_conf.reasons.append(ambiguity_reason)

        return best_conf
