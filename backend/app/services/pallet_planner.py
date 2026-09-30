"""Deterministic allocation of frozen approved lines; no AI or database reads."""
from decimal import Decimal, ROUND_FLOOR

from backend.app.schemas.pallet import PalletConfig
from backend.app.services.export_engine import expand_order_sheet_item, OrderExportError

MAX_PALLETS = 2000  # Operational output bound, not a company capacity rule.


def dec(value) -> Decimal:
    return Decimal(str(value))


def mass_per_unit(item: dict, weight_required: bool) -> Decimal | None:
    unit = item["unit"]
    if unit == "kg":
        return Decimal(1)
    if unit == "piece":
        value = item.get("kg_per_piece")
    elif unit == "case":
        value = item.get("kg_per_case")
        if value is None and item.get("kg_per_piece") is not None and item.get("pieces_per_case") is not None:
            value = dec(item["kg_per_piece"]) * dec(item["pieces_per_case"])
    else:
        value = None
    if value is None:
        if weight_required:
            raise OrderExportError(f"Cannot palletize SKU {item['sku']}: no frozen trusted physical weight for unit '{unit}'")
        return None
    result = dec(value)
    if not result.is_finite() or result <= 0:
        raise OrderExportError(f"Cannot palletize SKU {item['sku']}: invalid frozen physical weight")
    return result


def _chunk(item: dict, paid: Decimal, bonus: Decimal, mass: Decimal | None, policy: dict, business: dict) -> dict:
    copy = {**item, "quantity": float(paid), "bonus_quantity": float(bonus)}
    rows = expand_order_sheet_item(copy, policy, business, item["line_number"])
    return {
        "source_order_line_id": item.get("line_id"), "product_id": item.get("product_id"),
        "sku": item["sku"], "description": item["description"], "unit": item["unit"],
        "paid_quantity": str(paid), "bonus_quantity": str(bonus),
        "weight_kg": str((paid + bonus) * mass) if mass is not None else None,
        "output_row_count": len(rows), "rows": rows,
    }


def _row_usage(chunk: dict, mode: str) -> int:
    return chunk["output_row_count"] if mode == "output_rows" else 1


def _new_pallet(kind: str, group_name: str | None = None) -> dict:
    return {"pallet_number": 0, "type": kind, "group_name": group_name,
            "total_weight_kg": "0", "row_count": 0, "warnings": [], "items": []}


def _add(pallet: dict, chunk: dict, mode: str) -> None:
    pallet["items"].append(chunk)
    pallet["row_count"] += _row_usage(chunk, mode)
    if chunk["weight_kg"] is None:
        pallet["total_weight_kg"] = None
        warning = f"SKU {chunk['sku']} has no frozen trusted physical weight"
        if warning not in pallet["warnings"]:
            pallet["warnings"].append(warning)
    elif pallet["total_weight_kg"] is not None:
        pallet["total_weight_kg"] = str(dec(pallet["total_weight_kg"]) + dec(chunk["weight_kg"]))


def plan_pallets(items: list[dict], config: PalletConfig, policy: dict, business: dict) -> dict:
    """Preserve order and paid/bonus totals; dedicated membership precedes sequential packing."""
    if not config.enabled:
        raise ValueError("Pallet planning is disabled")
    automatic = config.automatic_pallets
    weight_limit = automatic.max_weight_kg
    row_limit = automatic.max_rows
    mode = automatic.row_count_mode
    pallets: list[dict] = []
    def finish(pallet: dict) -> None:
        if len(pallets) >= MAX_PALLETS:
            raise OrderExportError(f"Pallet plan exceeds the supported {MAX_PALLETS} pallets; increase capacity or split the order")
        pallets.append(pallet)
    membership = {pid: group.name for group in config.dedicated_groups for pid in group.product_ids}
    for group in config.dedicated_groups:
        selected = [item for item in items if item.get("product_id") in group.product_ids]
        if not selected:
            continue
        pallet = _new_pallet("dedicated", group.name)
        for item in selected:
            paid, bonus = dec(item["quantity"]), dec(item.get("bonus_quantity") or 0)
            mass = mass_per_unit(item, weight_limit is not None)
            _add(pallet, _chunk(item, paid, bonus, mass, policy, business), mode)
        if weight_limit is not None and pallet["total_weight_kg"] is not None and dec(pallet["total_weight_kg"]) > weight_limit:
            pallet["warnings"].append(f"Dedicated group exceeds automatic weight limit {weight_limit} kg")
        if row_limit is not None and pallet["row_count"] > row_limit:
            pallet["warnings"].append(f"Dedicated group exceeds automatic row limit {row_limit}")
        finish(pallet)

    current = _new_pallet("automatic")
    for item in items:
        if item.get("product_id") in membership:
            continue
        total_paid, total_bonus = dec(item["quantity"]), dec(item.get("bonus_quantity") or 0)
        if not total_paid.is_finite() or not total_bonus.is_finite() or total_paid <= 0 or total_bonus < 0:
            raise OrderExportError(f"Cannot palletize SKU {item['sku']}: invalid approved quantity")
        integer_unit = item["unit"] in {"piece", "case", "pallet"}
        if integer_unit and (total_paid != total_paid.to_integral_value() or total_bonus != total_bonus.to_integral_value()):
            raise OrderExportError(f"Cannot split SKU {item['sku']}: physical units must be whole")
        mass = mass_per_unit(item, weight_limit is not None)
        remaining_paid, remaining_bonus = total_paid, total_bonus
        while remaining_paid > 0:
            def make_candidate(take: Decimal) -> dict:
                if take == remaining_paid:
                    gift = remaining_bonus
                elif integer_unit:
                    # Cumulative proportional allocation keeps integer gift units and exact totals.
                    previously_paid = total_paid - remaining_paid
                    previously_bonus = total_bonus - remaining_bonus
                    target = ((previously_paid + take) * total_bonus / total_paid).to_integral_value(rounding=ROUND_FLOOR)
                    gift = max(Decimal(0), target - previously_bonus)
                else:
                    gift = remaining_bonus * take / remaining_paid
                return _chunk(item, take, gift, mass, policy, business)

            def fits(chunk: dict) -> bool:
                return ((row_limit is None or current["row_count"] + _row_usage(chunk, mode) <= row_limit)
                        and (weight_limit is None or dec(current["total_weight_kg"]) + dec(chunk["weight_kg"]) <= weight_limit))

            full = make_candidate(remaining_paid)
            if fits(full):
                chosen = full
                take = remaining_paid
            else:
                if row_limit is not None and current["row_count"] + _row_usage(full, mode) > row_limit and current["items"]:
                    finish(current)
                    current = _new_pallet("automatic")
                    continue
                if weight_limit is None:
                    if current["items"]:
                        finish(current)
                        current = _new_pallet("automatic")
                        continue
                    raise OrderExportError(f"Cannot palletize SKU {item['sku']}: one product allocation exceeds row capacity")
                available = weight_limit - dec(current["total_weight_kg"])
                if integer_unit:
                    high = min(remaining_paid, (available / mass).to_integral_value(rounding=ROUND_FLOOR))
                    low = Decimal(0)
                    chosen = None
                    # Binary search over whole physical units, with gifts included in every candidate.
                    while low < high:
                        mid = (low + high + 1) // 2
                        candidate = make_candidate(mid)
                        if fits(candidate):
                            low, chosen = mid, candidate
                        else:
                            high = mid - 1
                    take = low
                    if take and chosen is None:
                        chosen = make_candidate(take)
                else:
                    ratio = (remaining_paid + remaining_bonus) / remaining_paid
                    take = min(remaining_paid, available / (mass * ratio))
                    chosen = make_candidate(take) if take > 0 else None
                    if chosen is not None and not fits(chosen):
                        take = Decimal(0)
                if take <= 0 or chosen is None:
                    if current["items"]:
                        finish(current)
                        current = _new_pallet("automatic")
                        continue
                    raise OrderExportError(f"Cannot palletize SKU {item['sku']}: one physical unit or paid/free chunk exceeds pallet capacity")
            _add(current, chosen, mode)
            remaining_paid -= take
            remaining_bonus -= dec(chosen["bonus_quantity"])
            if remaining_paid > 0:
                finish(current)
                current = _new_pallet("automatic")
        if remaining_bonus != 0:
            raise OrderExportError(f"Cannot palletize SKU {item['sku']}: bonus conservation failed")
    if current["items"]:
        finish(current)
    for number, pallet in enumerate(pallets, 1):
        pallet["pallet_number"] = number
    for item in items:
        chunks = [chunk for pallet in pallets for chunk in pallet["items"] if chunk["source_order_line_id"] == item.get("line_id")]
        if sum((dec(chunk["paid_quantity"]) for chunk in chunks), Decimal(0)) != dec(item["quantity"]) or sum(
            (dec(chunk["bonus_quantity"]) for chunk in chunks), Decimal(0)) != dec(item.get("bonus_quantity") or 0):
            raise OrderExportError(f"Cannot palletize SKU {item['sku']}: quantity conservation failed")
    return {"pallets": pallets, "row_count_mode": mode, "layout": config.output.layout}


def plan_for_order(db, order, profile) -> tuple[dict, PalletConfig]:
    from backend.app.services.export_engine import profile_policy_for_order, business_policy_for_order
    policy = profile_policy_for_order(order, profile)
    frozen = isinstance(order.approved_snapshot, dict) and "lines" in order.approved_snapshot
    if frozen and str(profile.id) not in order.approved_snapshot.get("export_profiles", {}):
        raise OrderExportError("Palletized export requires a profile frozen when this order was approved")
    config = PalletConfig.model_validate(policy.get("palletization") or {"enabled": False})
    if not config.enabled:
        raise OrderExportError("Pallet planning is disabled for this order and profile")
    lines = sorted(order.lines, key=lambda line: line.line_number)
    if frozen:
        items = order.approved_snapshot["lines"]
    else:
        items = [{
            "line_id": line.id, "line_number": line.line_number,
            "product_id": line.matched_product_id,
            "sku": line.final_sku or (line.matched_product.sku if line.matched_product else ""),
            "description": line.matched_product.description if line.matched_product else line.product_phrase,
            "quantity": line.final_quantity if line.final_quantity is not None else line.requested_quantity,
            "bonus_quantity": line.final_bonus_quantity if line.final_bonus_quantity is not None else (line.bonus_quantity or line.calculated_bonus_quantity or 0),
            "unit": line.final_unit or line.requested_unit,
            "pieces_per_case": line.matched_packaging.pieces_per_case if line.matched_packaging else None,
            "kg_per_piece": str(line.matched_product.kg_per_piece) if line.matched_product and line.matched_product.kg_per_piece is not None else None,
            "kg_per_case": str(line.matched_packaging.kg_per_case) if line.matched_packaging and line.matched_packaging.kg_per_case is not None else None,
        } for line in lines]
    if len(items) != len(lines) or any(item.get("line_id") != line.id for item, line in zip(items, lines)):
        raise OrderExportError("Approved order lines differ from pallet snapshot")
    if any(not item.get("product_id") for item in items):
        raise OrderExportError("Pallet planning requires resolved catalog products")
    return plan_pallets(items, config, policy, business_policy_for_order(db, order)), config
