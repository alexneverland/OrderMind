"""Promotion calculation, tenant validation, AI proposal, and frozen provenance."""
import pytest
from copy import deepcopy
from pydantic import ValidationError
from sqlalchemy import select

from backend.app.models.business_settings import CompanyBusinessSettings, CompanyRule
from backend.app.models.company import Company
from backend.app.models.customer import Customer
from backend.app.models.order import Order
from backend.app.models.product import Product
from backend.app.models.export import ExportProfile
from backend.app.schemas.matching import ConfidenceResult, LineMatchResult, MatchDecision, MatchedProductInfo
from backend.app.schemas.rules import QuantityBonusConfig, RuleWrite, RulesAnalysis
from backend.app.services.company_rule_service import create_rule, evaluate_quantity_bonus
from backend.app.services.order_workflow_service import OrderApprovalError, OrderWorkflowService
from backend.app.services.rules_assistant import analyze_rule_description


def data(db):
    a, b = Company(name="A"), Company(name="B")
    db.add_all([a, b]); db.flush()
    ca = Customer(company_id=a.id, customer_code="A", customer_name="Buyer A")
    cb = Customer(company_id=b.id, customer_code="B", customer_name="Buyer B")
    pa = Product(company_id=a.id, sku="SKU", description="Product A", unit="piece")
    pb = Product(company_id=b.id, sku="SKU", description="Product B", unit="piece")
    db.add_all([ca, cb, pa, pb]); db.commit()
    return a, b, ca, cb, pa, pb


def config(mode="per_quantity", threshold=10, unit="piece", reward=1):
    return QuantityBonusConfig.model_validate({
        "trigger": {"mode": mode, "quantity": threshold, "unit": unit},
        "reward": {"quantity": reward, "unit": unit},
    })


@pytest.mark.parametrize("mode,quantity,expected", [
    ("per_quantity", 9, 0), ("per_quantity", 10, 1),
    ("per_quantity", 20, 2), ("per_quantity", 25, 2),
    ("greater_than", 30, 0), ("greater_than", 31, 2),
    ("greater_than", 100, 2), ("greater_or_equal", 29, 0),
    ("greater_or_equal", 30, 2),
])
def test_deterministic_thresholds_and_unit_match(db_session, mode, quantity, expected):
    a, _, ca, _, pa, _ = data(db_session)
    unit = "case" if mode == "per_quantity" else "piece"
    create_rule(db_session, a.id, RuleWrite(
        configuration=config(mode, 30 if mode != "per_quantity" else 10,
                             unit=unit, reward=2 if mode != "per_quantity" else 1),
    ))
    db_session.commit()
    result = evaluate_quantity_bonus(db_session, a.id, ca.id, pa.id, quantity, unit, 0)
    assert (result["calculated_bonus_quantity"] if result else 0) == expected
    assert evaluate_quantity_bonus(db_session, a.id, ca.id, pa.id, 100, "kg", 0) is None


def test_scope_and_configuration_reject_cross_company_and_invalid_values(db_session, client):
    a, b, ca, cb, pa, pb = data(db_session)
    create_rule(db_session, a.id, RuleWrite(product_id=pa.id, customer_id=ca.id, configuration=config()))
    db_session.commit()
    assert evaluate_quantity_bonus(db_session, a.id, ca.id, pa.id, 20, "piece", 0)["calculated_bonus_quantity"] == 2
    assert evaluate_quantity_bonus(db_session, a.id, ca.id, pb.id, 20, "piece", 0) is None
    assert evaluate_quantity_bonus(db_session, a.id, cb.id, pa.id, 20, "piece", 0) is None
    assert evaluate_quantity_bonus(db_session, b.id, cb.id, pb.id, 20, "piece", 0) is None
    bad = client.post(f"/api/v1/companies/{b.id}/rules", json={
        "rule_type": "quantity_bonus", "product_id": pa.id, "configuration": config().model_dump(),
    })
    assert bad.status_code == 400
    invalid = client.post(f"/api/v1/companies/{a.id}/rules", json={
        "rule_type": "quantity_bonus", "configuration": {
            "trigger": {"mode": "per_quantity", "quantity": 0, "unit": "case"},
            "reward": {"quantity": 1, "unit": "piece"},
        },
    })
    assert invalid.status_code == 422
    with pytest.raises(ValidationError):
        QuantityBonusConfig.model_validate({
            "trigger": {"mode": "greater_than", "quantity": float("nan"), "unit": "piece"},
            "reward": {"quantity": 1, "unit": "piece"},
        })
    with pytest.raises(ValidationError, match="same unit"):
        QuantityBonusConfig.model_validate({
            "trigger": {"mode": "per_quantity", "quantity": 10, "unit": "case"},
            "reward": {"quantity": 12, "unit": "piece"},
        })


def test_fractional_per_quantity_has_no_binary_rounding_loss(db_session):
    a, _, ca, _, pa, _ = data(db_session)
    create_rule(db_session, a.id, RuleWrite(configuration=config(threshold=0.1, unit="kg", reward=0.2)))
    db_session.commit()
    result = evaluate_quantity_bonus(db_session, a.id, ca.id, pa.id, 0.3, "kg", 0)
    assert result["calculated_bonus_quantity"] == pytest.approx(0.6)


def test_overlap_requires_review_and_does_not_stack(db_session):
    a, _, ca, _, pa, _ = data(db_session)
    create_rule(db_session, a.id, RuleWrite(configuration=config(threshold=10)))
    create_rule(db_session, a.id, RuleWrite(configuration=config(threshold=20)))
    db_session.commit()
    result = evaluate_quantity_bonus(db_session, a.id, ca.id, pa.id, 20, "piece", 0)
    assert result["requires_review"] is True
    assert result["calculated_bonus_quantity"] == 0
    assert len(result["matching_rule_ids"]) == 2


def test_explicit_bonus_conflict_and_approved_snapshot_survive_rule_disable(db_session):
    a, _, ca, _, pa, _ = data(db_session)
    db_session.add(CompanyBusinessSettings(company_id=a.id, bonus_enabled=True, bonus_expression_mode="paid_plus_bonus"))
    rule = create_rule(db_session, a.id, RuleWrite(product_id=pa.id, configuration=config()))
    db_session.commit()
    match = LineMatchResult(
        line_number=1, original_text="SKU 10+2", product_phrase="SKU",
        quantity=10, unit="piece", raw_unit="pieces", unit_explicit=True,
        quantity_text="10+2", bonus_quantity=2,
        best_match=MatchedProductInfo(product_id=pa.id, sku=pa.sku, description=pa.description, unit="piece"),
        confidence=ConfidenceResult(score=0.99, decision=MatchDecision.AUTO_ACCEPT, reasons=[]),
    )
    order = OrderWorkflowService.create_order_from_match(db_session, a.id, ca.id, "SKU 10+2", [match])
    line = order.lines[0]
    assert (line.bonus_quantity, line.calculated_bonus_quantity, line.final_bonus_quantity) == (2, 1, None)
    assert line.status == "needs_review"
    OrderWorkflowService.confirm_line(db_session, order.id, line.id)
    with pytest.raises(OrderApprovalError, match="promotion conflict"):
        OrderWorkflowService.approve_order(db_session, order.id)
    OrderWorkflowService.update_line_final_values(db_session, order.id, line.id, final_bonus_quantity=2)
    approved = OrderWorkflowService.approve_order(db_session, order.id)
    frozen = deepcopy(approved.approved_snapshot["lines"][0])
    assert (frozen["requested_bonus_quantity"], frozen["calculated_bonus_quantity"], frozen["final_bonus_quantity"], frozen["bonus_quantity"]) == (2, 1, 2, 2)
    assert frozen["promotion_result"]["applied_rule_id"] == rule.id
    rule.enabled = False
    db_session.commit()
    db_session.expire_all()
    assert OrderWorkflowService.get_canonical_order(db_session.get(Order, order.id)).items[0].quantity == 10
    assert db_session.get(Order, order.id).approved_snapshot["lines"][0] == frozen


def test_calculated_bonus_reaches_approved_snapshot_without_rewriting_customer_input(db_session, client):
    a, _, ca, _, pa, _ = data(db_session)
    rule = create_rule(db_session, a.id, RuleWrite(configuration=config()))
    db_session.commit()
    match = LineMatchResult(
        line_number=1, original_text="25 SKU", product_phrase="SKU",
        quantity=25, unit="unknown", unit_explicit=False, bonus_quantity=0,
        final_unit="piece",
        best_match=MatchedProductInfo(product_id=pa.id, sku=pa.sku, description=pa.description, unit="piece"),
        confidence=ConfidenceResult(score=0.99, decision=MatchDecision.AUTO_ACCEPT, reasons=[]),
    )
    order = OrderWorkflowService.create_order_from_match(db_session, a.id, ca.id, "25 SKU", [match])
    line = order.lines[0]
    assert line.requested_unit == "unknown"
    assert line.bonus_quantity == 0
    assert line.calculated_bonus_quantity == 2
    assert line.final_bonus_quantity is None
    approved = OrderWorkflowService.approve_order(db_session, order.id)
    snapshot = approved.approved_snapshot["lines"][0]
    assert snapshot["bonus_quantity"] == 2
    assert snapshot["requested_bonus_quantity"] == 0
    assert snapshot["promotion_result"]["applied_rule_id"] == rule.id
    updated = client.put(f"/api/v1/companies/{a.id}/rules/{rule.id}", json={"configuration": config(threshold=5).model_dump()})
    assert updated.status_code == 200, updated.text
    db_session.expire_all()
    assert db_session.get(Order, order.id).approved_snapshot["lines"][0]["bonus_quantity"] == 2
    assert db_session.get(Order, order.id).approved_snapshot["lines"][0]["promotion_result"]["rule_configuration"]["trigger"]["quantity"] == 10


def test_analysis_is_read_only_and_apply_is_explicit(db_session, client, monkeypatch):
    a, b, ca, _, pa, _ = data(db_session)
    async def fake_analysis(_description):
        return RulesAnalysis.model_validate({
            "settings_patch": {"bonus_enabled": True, "bonus_expression_mode": "paid_plus_bonus", "unitless_order_behavior": "piece"},
            "quantity_rules": [{"configuration": config().model_dump(), "product_reference": "SKU"}],
            "unsupported_rules": [{"text": "weather discounts", "reason": "No discount engine"}],
        })
    monkeypatch.setattr("backend.app.api.v1.companies.analyze_rule_description", fake_analysis)
    before = db_session.execute(select(CompanyRule)).scalars().all()
    response = client.post(f"/api/v1/companies/{a.id}/rules/analyze", json={"description": "Every 10 pieces of SKU gives 1 free piece"})
    assert response.status_code == 200, response.text
    proposal = response.json()
    assert proposal["quantity_rules"][0]["product_id"] == pa.id
    assert proposal["unsupported_rules"][0]["text"] == "weather discounts"
    assert db_session.execute(select(CompanyRule)).scalars().all() == before
    assert db_session.get(CompanyBusinessSettings, a.id) is None
    applied = client.post(f"/api/v1/companies/{a.id}/rules/apply-proposal", json={"proposal": proposal})
    assert applied.status_code == 200, applied.text
    assert applied.json()["settings"]["unitless_order_behavior"] == "piece"
    assert len(client.get(f"/api/v1/companies/{a.id}/rules").json()) == 1
    assert client.post(f"/api/v1/companies/{a.id}/rules/apply-proposal", json={"proposal": proposal}).status_code == 200
    assert len(client.get(f"/api/v1/companies/{a.id}/rules").json()) == 1
    assert client.get(f"/api/v1/companies/{b.id}/rules").json() == []


@pytest.mark.asyncio
async def test_selected_provider_returns_strict_supported_proposal(monkeypatch):
    class Provider:
        name = "openai"
        async def _complete(self, prompt, system_instruction):
            import json
            assert json.loads(prompt)["untrusted_text"] == "If no unit, use pieces. Weather discount"
            assert "never" in system_instruction.lower()
            return '{"settings_patch":{"unitless_order_behavior":"piece"},"quantity_rules":[],"export_patch":null,"unsupported_rules":[{"text":"weather discount","reason":"No discount engine"}]}'
    monkeypatch.setattr("backend.app.services.rules_assistant.get_ai_provider", lambda: Provider())
    result = await analyze_rule_description("If no unit, use pieces. Weather discount")
    assert result.settings_patch.unitless_order_behavior == "piece"
    assert result.unsupported_rules[0].text == "weather discount"
    with pytest.raises(ValidationError):
        RulesAnalysis.model_validate({"quantity_rules": [{"rule_type": "python", "configuration": {}}]})


def test_export_rule_stays_with_selected_profile_and_invalid_apply_rolls_back(db_session, client, monkeypatch):
    a, b, ca, _, pa, pb = data(db_session)
    one = ExportProfile(company_id=a.id, name="A sheet", format="order_sheet")
    two = ExportProfile(company_id=a.id, name="B sheet", format="order_sheet")
    foreign = ExportProfile(company_id=b.id, name="Foreign sheet", format="order_sheet")
    db_session.add_all([one, two, foreign]); db_session.commit()
    async def fake_analysis(_description):
        return RulesAnalysis.model_validate({
            "export_patch": {"bonus_separate_row": True, "bonus_marker": "A"},
        })
    monkeypatch.setattr("backend.app.api.v1.companies.analyze_rule_description", fake_analysis)
    proposal = client.post(f"/api/v1/companies/{a.id}/rules/analyze", json={"description": "Free goods on a separate row"}).json()
    assert proposal["export_patch"]["profile_id"] is None
    assert len(proposal["export_profile_candidates"]) == 2
    assert db_session.get(ExportProfile, one.id).bonus_separate_row is False
    assert client.post(f"/api/v1/companies/{a.id}/rules/apply-proposal", json={"proposal": proposal}).status_code == 400
    proposal["export_patch"]["profile_id"] = foreign.id
    assert client.post(f"/api/v1/companies/{a.id}/rules/apply-proposal", json={"proposal": proposal}).status_code == 400
    proposal["export_patch"]["profile_id"] = one.id
    applied = client.post(f"/api/v1/companies/{a.id}/rules/apply-proposal", json={"proposal": proposal})
    assert applied.status_code == 200, applied.text
    db_session.refresh(one); db_session.refresh(two)
    assert (one.bonus_separate_row, one.bonus_marker) == (True, "A")
    assert two.bonus_separate_row is False

    # A bad second item must roll back a valid first rule and settings patch.
    proposal = {
        "settings_patch": {"unitless_order_behavior": "piece"},
        "quantity_rules": [
            {"configuration": config().model_dump(), "product_id": pa.id},
            {"configuration": config().model_dump(), "product_id": pb.id},
        ], "export_patch": None, "export_profile_candidates": [], "unsupported_rules": [],
    }
    bad = client.post(f"/api/v1/companies/{a.id}/rules/apply-proposal", json={"proposal": proposal})
    assert bad.status_code == 400
    assert db_session.execute(select(CompanyRule).where(CompanyRule.company_id == a.id)).scalars().all() == []
    assert db_session.get(CompanyBusinessSettings, a.id).unitless_order_behavior == "require_review"


def promotion_order(db, company, customer, product, quantity=20, unit="piece", bonus=0):
    match = LineMatchResult(
        line_number=1, original_text=f"{quantity} SKU", product_phrase="SKU",
        quantity=quantity, unit=unit, raw_unit=unit, unit_explicit=True,
        quantity_text=f"{quantity}+{bonus}" if bonus else None, bonus_quantity=bonus,
        best_match=MatchedProductInfo(product_id=product.id, sku=product.sku,
                                      description=product.description, unit=product.unit),
        confidence=ConfidenceResult(score=0.99, decision=MatchDecision.AUTO_ACCEPT, reasons=[]),
    )
    return OrderWorkflowService.create_order_from_match(
        db, company.id, customer.id, f"{quantity} SKU", [match]
    )


@pytest.mark.parametrize("old_override,new_quantity,new_calculated", [
    (3, 40, 4), (2, 30, 3), (3, 5, 0),
])
def test_quantity_change_clears_stale_promotion_override(
    db_session, old_override, new_quantity, new_calculated
):
    a, _, ca, _, pa, _ = data(db_session)
    create_rule(db_session, a.id, RuleWrite(product_id=pa.id, configuration=config()))
    db_session.commit()
    order = promotion_order(db_session, a, ca, pa)
    line = order.lines[0]
    OrderWorkflowService.update_line_final_values(
        db_session, order.id, line.id, final_bonus_quantity=old_override
    )
    changed = OrderWorkflowService.update_line_final_values(
        db_session, order.id, line.id, final_quantity=new_quantity
    )
    assert changed.calculated_bonus_quantity == new_calculated
    assert changed.final_bonus_quantity is None
    assert (changed.promotion_result is None) == (new_quantity == 5)
    assert changed.bonus_quantity == 0


def test_same_patch_bonus_is_a_fresh_choice_and_manual_bonus_without_rule_survives(db_session):
    a, _, ca, _, pa, _ = data(db_session)
    create_rule(db_session, a.id, RuleWrite(product_id=pa.id, configuration=config()))
    db_session.commit()
    order = promotion_order(db_session, a, ca, pa)
    line = order.lines[0]
    OrderWorkflowService.update_line_final_values(db_session, order.id, line.id, final_bonus_quantity=3)
    changed = OrderWorkflowService.update_line_final_values(
        db_session, order.id, line.id, final_quantity=40, final_bonus_quantity=5
    )
    assert (changed.calculated_bonus_quantity, changed.final_bonus_quantity) == (4, 5)
    create_rule(db_session, a.id, RuleWrite(product_id=pa.id, configuration=config(threshold=100)))
    db_session.commit()
    no_rule = promotion_order(db_session, a, ca, pa, quantity=1)
    manual = OrderWorkflowService.update_line_final_values(
        db_session, no_rule.id, no_rule.lines[0].id, final_bonus_quantity=7
    )
    updated = OrderWorkflowService.update_line_final_values(
        db_session, no_rule.id, manual.id, final_quantity=2
    )
    assert updated.promotion_result is None
    assert updated.final_bonus_quantity == 7


def test_input_change_invalidates_override_even_if_calculated_award_is_equal(db_session):
    a, _, ca, _, pa, _ = data(db_session)
    create_rule(db_session, a.id, RuleWrite(product_id=pa.id, configuration=config()))
    db_session.commit()
    order = promotion_order(db_session, a, ca, pa)
    line = order.lines[0]
    OrderWorkflowService.update_line_final_values(db_session, order.id, line.id, final_bonus_quantity=3)
    changed = OrderWorkflowService.update_line_final_values(
        db_session, order.id, line.id, final_quantity=25
    )
    assert changed.calculated_bonus_quantity == 2
    assert changed.final_bonus_quantity is None


def test_fresh_bonus_in_same_patch_resolves_new_conflict_without_extra_review(db_session):
    a, _, ca, _, pa, _ = data(db_session)
    db_session.add(CompanyBusinessSettings(company_id=a.id, bonus_enabled=True, bonus_expression_mode="paid_plus_bonus"))
    create_rule(db_session, a.id, RuleWrite(product_id=pa.id, configuration=config()))
    db_session.commit()
    order = promotion_order(db_session, a, ca, pa, quantity=20, bonus=2)
    line = order.lines[0]
    OrderWorkflowService.confirm_line(db_session, order.id, line.id)
    changed = OrderWorkflowService.update_line_final_values(
        db_session, order.id, line.id, final_quantity=30, final_bonus_quantity=5
    )
    assert changed.promotion_result["requires_review"] is True
    assert (changed.calculated_bonus_quantity, changed.final_bonus_quantity) == (3, 5)
    assert changed.status == "confirmed"
    assert OrderWorkflowService.approve_order(db_session, order.id).status == "approved"


def test_unit_and_product_change_clear_stale_bonus(db_session):
    a, _, ca, _, pa, _ = data(db_session)
    pa.unit = "case"
    other = Product(company_id=a.id, sku="OTHER", description="Other", unit="case")
    db_session.add(other)
    create_rule(db_session, a.id, RuleWrite(product_id=pa.id, configuration=config(unit="case")))
    db_session.commit()
    order = promotion_order(db_session, a, ca, pa, unit="case")
    line = order.lines[0]
    OrderWorkflowService.update_line_final_values(db_session, order.id, line.id, final_bonus_quantity=3)
    changed = OrderWorkflowService.update_line_final_values(
        db_session, order.id, line.id, final_unit="piece"
    )
    assert (changed.promotion_result, changed.calculated_bonus_quantity, changed.final_bonus_quantity) == (None, 0, None)
    OrderWorkflowService.update_line_final_values(db_session, order.id, line.id, final_unit="case", final_bonus_quantity=3)
    _, corrected = OrderWorkflowService.correct_line(db_session, order.id, line.id, other.id)
    assert corrected.matched_product_id == other.id
    assert (corrected.promotion_result, corrected.calculated_bonus_quantity, corrected.final_bonus_quantity) == (None, 0, None)


def test_rule_change_with_same_award_invalidates_override_and_refreshes_pending(db_session, client):
    a, _, ca, _, pa, _ = data(db_session)
    first = create_rule(db_session, a.id, RuleWrite(product_id=pa.id, configuration=config(threshold=10, reward=1)))
    db_session.commit()
    order = promotion_order(db_session, a, ca, pa)
    line = order.lines[0]
    OrderWorkflowService.update_line_final_values(db_session, order.id, line.id, final_bonus_quantity=3)
    assert line.calculated_bonus_quantity == 2
    replacement = client.post(f"/api/v1/companies/{a.id}/rules", json={
        "product_id": pa.id, "configuration": config(threshold=20, reward=2).model_dump(),
    })
    assert replacement.status_code == 201, replacement.text
    assert client.delete(f"/api/v1/companies/{a.id}/rules/{first.id}").status_code == 204
    db_session.refresh(line)
    assert line.promotion_result["applied_rule_id"] == replacement.json()["id"]
    assert line.calculated_bonus_quantity == 2
    assert line.final_bonus_quantity is None


def test_rule_update_refreshes_pending_and_approval_checks_current_promotion(db_session, client):
    a, _, ca, _, pa, _ = data(db_session)
    rule = create_rule(db_session, a.id, RuleWrite(product_id=pa.id, configuration=config()))
    db_session.commit()
    order = promotion_order(db_session, a, ca, pa)
    line = order.lines[0]
    OrderWorkflowService.update_line_final_values(db_session, order.id, line.id, final_bonus_quantity=3)
    updated = client.put(f"/api/v1/companies/{a.id}/rules/{rule.id}", json={
        "configuration": config(threshold=5).model_dump(),
    })
    assert updated.status_code == 200, updated.text
    db_session.refresh(line)
    assert line.calculated_bonus_quantity == 4
    assert line.final_bonus_quantity is None
    line.calculated_bonus_quantity = 2
    line.promotion_result = {**line.promotion_result, "calculated_bonus_quantity": 2}
    db_session.commit()
    with pytest.raises(OrderApprovalError, match="changed promotion rules"):
        OrderWorkflowService.approve_order(db_session, order.id)


def test_disabling_rule_removes_pending_bonus_before_approval(db_session, client):
    a, _, ca, _, pa, _ = data(db_session)
    rule = create_rule(db_session, a.id, RuleWrite(product_id=pa.id, configuration=config()))
    db_session.commit()
    order = promotion_order(db_session, a, ca, pa)
    line = order.lines[0]
    OrderWorkflowService.update_line_final_values(db_session, order.id, line.id, final_bonus_quantity=3)
    assert client.delete(f"/api/v1/companies/{a.id}/rules/{rule.id}").status_code == 204
    db_session.refresh(line)
    assert (line.promotion_result, line.calculated_bonus_quantity, line.final_bonus_quantity) == (None, 0, None)
    assert OrderWorkflowService.approve_order(db_session, order.id).approved_snapshot["lines"][0]["bonus_quantity"] == 0


def test_approval_refreshes_legacy_stale_promotion_then_requires_retry(db_session):
    a, _, ca, _, pa, _ = data(db_session)
    order = promotion_order(db_session, a, ca, pa)
    line = order.lines[0]
    assert line.promotion_result is None
    # Simulate a pending order saved before the promotion existed.
    rule = create_rule(db_session, a.id, RuleWrite(product_id=pa.id, configuration=config()))
    db_session.commit()
    with pytest.raises(OrderApprovalError, match="recalculated"):
        OrderWorkflowService.approve_order(db_session, order.id)
    db_session.refresh(line)
    db_session.refresh(order)
    assert order.status == "pending_review"
    assert order.approved_snapshot is None
    assert (line.promotion_result["applied_rule_id"], line.calculated_bonus_quantity) == (rule.id, 2)
    assert line.bonus_quantity == 0
    approved = OrderWorkflowService.approve_order(db_session, order.id)
    assert approved.approved_snapshot["lines"][0]["bonus_quantity"] == 2


def test_approval_refreshes_conflict_without_approving_or_preserving_override(db_session):
    a, _, ca, _, pa, _ = data(db_session)
    db_session.add(CompanyBusinessSettings(company_id=a.id, bonus_enabled=True, bonus_expression_mode="paid_plus_bonus"))
    db_session.commit()
    order = promotion_order(db_session, a, ca, pa, bonus=3)
    line = order.lines[0]
    OrderWorkflowService.update_line_final_values(db_session, order.id, line.id, final_bonus_quantity=3)
    create_rule(db_session, a.id, RuleWrite(product_id=pa.id, configuration=config()))
    db_session.commit()
    with pytest.raises(OrderApprovalError, match="recalculated"):
        OrderWorkflowService.approve_order(db_session, order.id)
    db_session.refresh(line)
    assert line.promotion_result["requires_review"] is True
    assert line.status == "needs_review"
    assert line.bonus_quantity == 3
    assert line.final_bonus_quantity is None
    with pytest.raises(OrderApprovalError, match="still require review"):
        OrderWorkflowService.approve_order(db_session, order.id)


def test_new_conflict_requires_review_and_blocks_approval_until_decision(db_session, client):
    a, _, ca, _, pa, _ = data(db_session)
    create_rule(db_session, a.id, RuleWrite(product_id=pa.id, configuration=config(threshold=10)))
    db_session.commit()
    order = promotion_order(db_session, a, ca, pa)
    line = order.lines[0]
    OrderWorkflowService.update_line_final_values(db_session, order.id, line.id, final_bonus_quantity=3)
    added = client.post(f"/api/v1/companies/{a.id}/rules", json={
        "product_id": pa.id, "configuration": config(threshold=20).model_dump(),
    })
    assert added.status_code == 201, added.text
    db_session.refresh(line)
    assert line.promotion_result["requires_review"] is True
    assert line.final_bonus_quantity is None
    assert line.status == "needs_review"
    with pytest.raises(OrderApprovalError):
        OrderWorkflowService.approve_order(db_session, order.id)
