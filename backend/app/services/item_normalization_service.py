import copy
import re
from decimal import Decimal, InvalidOperation
from difflib import SequenceMatcher
from typing import Any

from app.config import settings
from app.schemas.invoice_parser import InvoiceItemPackage, NormalizedInvoiceItem, PackagingFact


_CODE_RE = re.compile(r"(?<![A-ZА-ЯЁ0-9])(?:[NM]\+|\+)\d+", re.IGNORECASE)
_DIMENSION_RE = re.compile(r"\b\d+(?:[.,]\d+)?\s*[*XХ]\s*\d+(?:[.,]\d+)?\s*СМ\b", re.IGNORECASE)
_COMPOUND_PACKAGE_RE = re.compile(
    r"\b(?P<count>\d+(?:[.,]\d+)?)\s*[XХ]\s*(?P<value>\d+(?:[.,]\d+)?)\s*"
    r"(?P<unit>КГ|Г|МЛ|Л|ШТ|ПАК)\b",
    re.IGNORECASE,
)
_PACKAGE_RE = re.compile(
    r"\b(?P<value>\d+(?:[.,]\d+)?)\s*(?P<unit>КГ|Г|МЛ|Л|ШТ|ПАК)\b",
    re.IGNORECASE,
)
_TECHNICAL_PREFIX_RE = re.compile(
    r"^\s*(?:\d+\s+)?(?:(?:ТОВАР|ПОЗИЦИЯ|АРТИКУЛ)\s*[:.-]?\s*)*"
    r"(?:(?:ШТ|КГ|Л|УПАК)\.?\s*[:.-]?\s*)*",
    re.IGNORECASE,
)
_PROMO_PACKAGING_TOKEN_RE = re.compile(
    r"\b(?:ВИКТОРИЯ|МАЙКА|ПАКЕТ-МАЙКА|ПАКЕТ|ФАС|ФАС\.|УПАК|УПАК\.|ПРОМО)\b",
    re.IGNORECASE,
)

_UNIT_ALIASES = {
    "Г": "г",
    "ГР": "г",
    "ГР.": "г",
    "КГ": "кг",
    "КГ.": "кг",
    "KT": "кг",
    "KR": "кг",
    "МЛ": "мл",
    "Л": "л",
    "ШТ": "шт",
    "ШТ.": "шт",
    "ПАК": "пак",
    "УП": "упак",
    "УПАК": "упак",
    "УПАК.": "упак",
    "ЯЩ": "ящ",
    "КОРОБ": "короб",
    "БУТ": "бут",
}

_METHOD_NO_RECALC = {"без пересчета", "без пересчёта"}
_METHOD_BY_UNITS = {"по количеству вложений", "по вложениям"}
_METHOD_BY_WEIGHT = {"по весу/объему", "по весу/объёму", "по весу", "по объему", "по объёму"}
_METHOD_BY_DRY_WEIGHT = {"по сухому весу"}
_METHOD_BY_COEFFICIENT = {"по коэффициенту", "по коэффициенту пересчета"}
_METHOD_BY_AVG_WEIGHT = {"по среднему весу штуки", "по среднему весу"}
_METHOD_MANUAL = {"ручная проверка"}

_RULE_ACTIVE = "active"
_RULE_INACTIVE = "inactive"
_RULE_NEEDS_REVIEW = "review"


def normalize_item_candidate(item: NormalizedInvoiceItem) -> list[dict[str, str]]:
    """Normalize one model candidate and return deterministic review issues."""
    issues: list[dict[str, str]] = []
    raw_name = _clean_spaces(item.raw_name)
    item.raw_name = raw_name

    extracted_codes = _CODE_RE.findall(raw_name)
    item.codes = _deduplicate([*item.codes, *extracted_codes])

    package, multiplier, accounting_unit = _extract_package(raw_name)
    if package.raw:
        item.package = package
    else:
        item.package = _package_from_facts(item.packaging_facts)

    document_unit = _normalize_document_unit(item.document_unit or item.unit)
    item.document_unit = document_unit
    item.unit = document_unit
    quantity = _number(item.quantity_document if item.quantity_document is not None else item.quantity)
    item.quantity_document = quantity
    item.quantity = quantity

    clean_name = _clean_product_name(raw_name, item.package.raw)
    item.clean_name = clean_name or _clean_product_name(item.clean_name, item.package.raw)
    item.normalized_name_candidate = _readable_name(
        _clean_product_name(item.normalized_name_candidate, item.package.raw) or item.clean_name
    )
    item.brand_or_descriptor = _clean_spaces(item.brand_or_descriptor)

    if multiplier is None:
        multiplier, accounting_unit = _fallback_multiplier(item.package, document_unit)
    units_per_package = _positive_number(item.units_per_package)
    if units_per_package is None:
        units_per_package = _positive_number(_units_per_package_from_facts(item.packaging_facts))
    item.units_per_package = units_per_package
    multiplier = _apply_units_per_package(multiplier, units_per_package)
    item.quantity_multiplier = multiplier
    item.accounting_unit_candidate = accounting_unit or _normalize_unit(item.accounting_unit_candidate)
    item.accounting_quantity_candidate = _multiply(quantity, multiplier)

    if re.search(r"\b(?:САЛФЕТК|ЛИСТ)", item.clean_name, re.IGNORECASE) and item.package.unit == "л":
        issues.append(_issue("package", "Единица «л» может означать листы, а не литры."))
    if item.needs_review:
        issues.append(_issue("item_normalization", item.review_reason or "Модель отметила строку для проверки."))
    if item.confidence is not None and item.confidence < 0.8:
        issues.append(_issue("confidence", item.review_reason or "Низкая уверенность распознавания товарной строки."))
    if not item.clean_name:
        issues.append(_issue("clean_name", "Не удалось очистить наименование товара."))
    if multiplier is None or not item.accounting_unit_candidate:
        issues.append(_issue("package", "Не удалось уверенно определить фасовку или единицу учета."))

    if issues:
        item.needs_review = True
        item.review_reason = item.review_reason or issues[0]["reason"]
        if item.confidence is None or item.confidence >= 0.8:
            item.confidence = 0.79
    return _deduplicate_issues(issues)


def apply_reference_mapping_to_payload(
    payload: dict[str, Any],
    *,
    products: list[dict[str, Any]],
    packages: list[dict[str, Any]],
    conversion_exceptions: list[dict[str, Any]] | None = None,
    warehouse: str | None = None,
) -> dict[str, Any]:
    """Map parser candidates to sheet references without model involvement."""
    result = copy.deepcopy(payload)
    metadata = result.setdefault("parser_metadata", {})
    review_flags = metadata.setdefault("review_flags", [])
    corrections = metadata.setdefault("item_corrections", {})
    parser_notes = result.setdefault("parser_notes", [])
    conversion_exceptions = conversion_exceptions or []
    rules = _merge_rule_sources(packages, conversion_exceptions)
    supplier_inn = str(result.get("supplier_inn") or "")
    supplier_name = str(result.get("supplier") or result.get("supplier_legal_name") or "")

    for index, item in enumerate(result.get("items") or [], start=1):
        line_number = int(item.get("line_number") or index)
        item["us_product_name"] = _fallback_us_product_name(item)
        product_match = _match_product(item, products)
        product_unit = ""

        if product_match["status"] == "matched":
            item["us_product_name"] = product_match["name"]
            item["product_code"] = product_match.get("code")
            item["product_found"] = "Да"
            product_unit = product_match.get("unit") or ""
        elif product_match["status"] == "ambiguous":
            item["product_found"] = "?"
            _add_mapping_problem(
                item,
                line_number,
                "normalized_name_candidate",
                "Товар требует подтверждения сопоставления со справочником «Товары».",
                "Сопоставление",
                review_flags,
                corrections,
                parser_notes,
            )
        else:
            item["product_found"] = "Нет"
            _add_mapping_problem(
                item,
                line_number,
                "normalized_name_candidate",
                "Товар не найден в справочнике «Товары».",
                "Нет в справочнике",
                review_flags,
                corrections,
                parser_notes,
            )

        resolution = _resolve_conversion(
            item,
            product_match,
            rules,
            warehouse=warehouse,
            supplier_inn=supplier_inn,
            supplier_name=supplier_name,
        )
        multiplier = resolution.get("multiplier")
        accounting_unit = resolution.get("accounting_unit") or ""
        conversion_method = resolution.get("method") or "unresolved"
        rule_id = resolution.get("rule_id")

        if resolution["status"] in {"ambiguous", "manual", "unresolved"}:
            multiplier = None
            accounting_unit = ""
            conversion_method = "unresolved"
            if resolution.get("stored_conversion_factor") is not None:
                item["stored_conversion_factor"] = resolution["stored_conversion_factor"]
            _add_mapping_problem(
                item,
                line_number,
                "conversion_factor",
                resolution.get("reason") or "Не удалось детерминированно рассчитать пересчет количества.",
                "Сопоставление",
                review_flags,
                corrections,
                parser_notes,
            )
        elif resolution["status"] == "no_rule":
            note = resolution.get("reason") or "Правило пересчета не найдено, количество оставлено без пересчета."
            if note not in parser_notes:
                parser_notes.append(note)
            flag = {
                "scope": "item",
                "line_number": line_number,
                "field": "conversion_factor",
                "reason": note,
                "severity": "warning",
            }
            if flag not in review_flags:
                review_flags.append(flag)
        elif product_unit and accounting_unit and product_unit != accounting_unit and rule_id is None:
            multiplier = None
            accounting_unit = ""
            conversion_method = "unresolved"
            _add_mapping_problem(
                item,
                line_number,
                "accounting_unit_candidate",
                "Единица расчета не совпадает с единицей товара в «Товары», а подтверждающее правило не найдено.",
                "Сопоставление",
                review_flags,
                corrections,
                parser_notes,
            )
        elif product_unit:
            accounting_unit = product_unit

        if rule_id is not None:
            item["package_reference_id"] = rule_id
            item["conversion_source_id"] = rule_id

        if multiplier is not None and multiplier <= 0:
            multiplier = None
            _add_mapping_problem(
                item,
                line_number,
                "conversion_factor",
                "Коэффициент пересчета должен быть больше нуля.",
                "Сопоставление",
                review_flags,
                corrections,
                parser_notes,
            )

        # `units_per_package` (AI-extracted count_in_package fact, e.g. "250 шт
        # в упаковке") is recorded for display in "Состав упаковки" always,
        # but only folded into `multiplier` when an active rule (`rule_id`)
        # actually confirmed this item's conversion -- e.g. a case of N
        # rule-confirmed bottles. Without a matching rule, `_resolve_conversion`
        # already returned the safe identity default (1.0); re-applying
        # `units_per_package` on top of that unconditionally, regardless of
        # whether any rule confirmed anything, silently undid that safety net
        # -- e.g. 3 packs of napkins x 250 = 750 with no rule involved at all
        # (real production bug, Lilia's 2026-07-24 Metro feedback).
        units_per_package = _positive_number(item.get("units_per_package"))
        item["units_per_package"] = units_per_package
        if rule_id is not None:
            multiplier = _apply_units_per_package(multiplier, units_per_package)
            conversion_method = _package_method(conversion_method, units_per_package)

        quantity = _number(item.get("quantity_document"))
        if quantity is None:
            quantity = _number(item.get("quantity"))
        item["quantity_multiplier"] = multiplier
        item["conversion_factor"] = multiplier
        item["conversion_method"] = conversion_method if multiplier is not None else "unresolved"
        item["us_unit"] = accounting_unit or ""
        item["quantity_us"] = _multiply(quantity, multiplier)
        price = _number(item.get("price"))
        item["price_us"] = _divide(price, multiplier)
        item["conversion_amount_delta"] = _conversion_amount_delta(
            quantity,
            price,
            item["quantity_us"],
            item["price_us"],
        )
        if (
            item["conversion_amount_delta"] is not None
            and item["conversion_amount_delta"] > settings.conversion_amount_tolerance
        ):
            _add_mapping_problem(
                item,
                line_number,
                "price_us",
                "Пересчитанные количество и цена не сохраняют стоимость строки.",
                "Сопоставление",
                review_flags,
                corrections,
                parser_notes,
            )
        if multiplier is None or not accounting_unit:
            item["conversion_review_reason"] = (
                item.get("review_reason")
                or "Не удалось детерминированно рассчитать количество и цену в УС."
            )
        elif item["price_us"] is None and price is not None:
            item["conversion_review_reason"] = "Цена в УС не рассчитана, хотя коэффициент определен."
            _add_mapping_problem(
                item,
                line_number,
                "price_us",
                item["conversion_review_reason"],
                "Сопоставление",
                review_flags,
                corrections,
                parser_notes,
            )
        item["mapping_status"] = "needs_review" if item.get("correction") else "ready"
        item["mapping_error"] = item.get("review_reason") if item.get("correction") else ""

    if corrections and metadata.get("upload_status") != "Не готово":
        metadata["upload_status"] = "Требует проверки"
        if metadata.get("duplicate") != "Да":
            metadata["row_status"] = "Правка вручную"
    return result


def _calculate_conversion(item: dict[str, Any]) -> tuple[float | None, str, str]:
    raw_name = str(item.get("raw_name") or item.get("name") or "")
    document_unit = _normalize_unit(item.get("document_unit") or item.get("unit"))
    package, multiplier, accounting_unit = _extract_package(raw_name)
    if multiplier is not None:
        if document_unit in {"кг", "л"} and accounting_unit == document_unit and multiplier > 1:
            return 1.0, document_unit, "identity_document_unit"
        method = "compound_package" if _COMPOUND_PACKAGE_RE.search(raw_name) else "standard"
        return multiplier, accounting_unit, method

    package_data = item.get("package") if isinstance(item.get("package"), dict) else {}
    package_value = _number(package_data.get("value"))
    package_unit = _normalize_unit(package_data.get("unit"))
    multiplier, accounting_unit = _convert_package_value(package_value, package_unit)
    if multiplier is not None:
        return multiplier, accounting_unit, "standard"

    if document_unit in {"кг", "л", "шт", "бут"}:
        return 1.0, document_unit, "identity"
    if package.raw:
        return None, "", "unresolved"
    return None, "", "unresolved"


def _merge_rule_sources(*sources: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    """Combine package/exception reference rows into one deduplicated rule list.

    `Справочник фасовок` and a legacy separate exceptions sheet may both be
    configured; rows are deduplicated so the same physical rule row read from
    two ranges is not matched twice.
    """
    seen: set[tuple[tuple[str, Any], ...]] = set()
    merged: list[dict[str, Any]] = []
    for source in sources:
        for row in source or []:
            try:
                key = tuple(sorted(row.items()))
            except TypeError:
                key = None
            if key is not None:
                if key in seen:
                    continue
                seen.add(key)
            merged.append(row)
    return merged


def _resolve_conversion(
    item: dict[str, Any],
    product_match: dict[str, Any],
    rules: list[dict[str, Any]],
    *,
    warehouse: str | None = None,
    supplier_inn: str | None = None,
    supplier_name: str | None = None,
) -> dict[str, Any]:
    """Determine the final Кол-во в УС conversion for one item.

    A `Справочник фасовок` / `Правила фасовок` row is authoritative when
    found. Package-shaped text in the name (`0,5Л 12ШТ`, `12 РУЛ`, ...) is
    only ever a *candidate*: without a matching active rule, the accounting
    quantity defaults to the document quantity unchanged (`identity_no_rule`)
    instead of silently decomposing it. Document-unit identity (`document_unit`
    already equal to the accounting unit, e.g. goods sold by weight in `кг`)
    is safe without a rule because no package-based guess is involved.
    """
    document_unit = _normalize_unit(item.get("document_unit") or item.get("unit"))
    computed_multiplier, computed_unit, computed_method = _calculate_conversion(item)
    rule_match = _match_conversion_rule(
        item,
        product_match,
        rules,
        document_unit=document_unit,
        warehouse=warehouse,
        supplier_inn=supplier_inn,
        supplier_name=supplier_name,
    )

    if rule_match["status"] == "ambiguous":
        return {"status": "ambiguous", "reason": "Найдено несколько подходящих правил пересчета одинаковой точности."}

    if rule_match["status"] == "matched":
        rule = rule_match["rule"]
        match_kind = rule_match["match_kind"]
        rule_id = _catalog_value(rule, "ID", "ID правила", "id")
        method_label = _normalize_method_label(
            _catalog_value(rule, "Способ пересчета", "Режим пересчета", "conversion_method")
        )
        rule_factor = _number(
            _catalog_value(
                rule,
                "Коэффициент пересчета",
                "Коэффициент",
                "Вес 1 шт",
                "Вес / объем единицы",
                "factor",
            )
        )
        rule_unit = _normalize_unit(
            _catalog_value(rule, "Единица учета в УС", "Ед.изм. в УС", "Ед. изм. в УС", "accounting_unit")
        )

        if method_label in _METHOD_MANUAL:
            return {"status": "manual", "reason": "Правило пересчета требует ручной проверки."}

        if method_label in _METHOD_NO_RECALC:
            return {
                "status": "resolved",
                "multiplier": 1.0,
                "accounting_unit": rule_unit or document_unit,
                "method": "no_recalculation_rule",
                "rule_id": rule_id,
            }

        if method_label in _METHOD_BY_DRY_WEIGHT:
            dry_multiplier, dry_unit = _dry_weight_multiplier(item)
            if dry_multiplier is None:
                return {
                    "status": "unresolved",
                    "reason": "Правило требует пересчета по сухому весу, но сухой вес не указан в документе.",
                }
            return {
                "status": "resolved",
                "multiplier": dry_multiplier,
                "accounting_unit": rule_unit or dry_unit,
                "method": "dry_weight_rule",
                "rule_id": rule_id,
            }

        if method_label in _METHOD_BY_UNITS:
            multiplier = rule_factor if rule_factor is not None else computed_multiplier
            if multiplier is None:
                return {
                    "status": "unresolved",
                    "reason": "Не удалось определить коэффициент пересчета по количеству вложений.",
                }
            return {
                "status": "resolved",
                "multiplier": multiplier,
                "accounting_unit": rule_unit or computed_unit or document_unit,
                "method": "package_units_rule",
                "rule_id": rule_id,
            }

        if method_label in _METHOD_BY_WEIGHT:
            multiplier = rule_factor if rule_factor is not None else computed_multiplier
            if multiplier is None:
                return {
                    "status": "unresolved",
                    "reason": "Не удалось определить коэффициент пересчета по весу/объему.",
                }
            return {
                "status": "resolved",
                "multiplier": multiplier,
                "accounting_unit": rule_unit or computed_unit,
                "method": "weight_volume_rule",
                "rule_id": rule_id,
            }

        if method_label in _METHOD_BY_COEFFICIENT:
            # The rule's own confirmed coefficient only -- never fall back to
            # the computed/regex guess, per explicit tester requirement that
            # AI/code must never invent this value.
            if rule_factor is None:
                return {
                    "status": "unresolved",
                    "reason": "Правило требует коэффициент, но он не задан.",
                }
            return {
                "status": "resolved",
                "multiplier": rule_factor,
                "accounting_unit": rule_unit or computed_unit or document_unit,
                "method": "coefficient_rule",
                "rule_id": rule_id,
            }

        if method_label in _METHOD_BY_AVG_WEIGHT:
            # Average weight per piece (avocado/lettuce/microgreens style):
            # only the rule's own confirmed average is used today. A real
            # scale-printed weight on the document should override this once
            # an `actual_weight` packaging fact is wired through -- not done
            # yet, deliberately deferred (see docs/wiki/unit-conversion-rules.md).
            if rule_factor is None:
                return {
                    "status": "unresolved",
                    "reason": "Правило пересчета по среднему весу штуки не содержит веса.",
                }
            return {
                "status": "resolved",
                "multiplier": rule_factor,
                "accounting_unit": rule_unit or document_unit,
                "method": "average_weight_rule",
                "rule_id": rule_id,
            }

        # Legacy `Справочник фасовок` rows with no `Способ пересчета` value yet.
        if match_kind == "product":
            # Product-identity exception (eggs/avocado/olives style): the
            # rule's own factor always wins, the computed guess is not
            # comparable (usually just an identity default).
            if rule_factor is None:
                return {"status": "unresolved", "reason": "Правило пересчета не содержит коэффициента."}
            return {
                "status": "resolved",
                "multiplier": rule_factor,
                "accounting_unit": rule_unit or computed_unit or document_unit,
                "method": "product_exception",
                "rule_id": rule_id,
            }

        # Package-text match: keep the pre-existing behavior of confirming
        # the computed physical conversion against a stored coefficient, or
        # filling in when nothing was computed.
        if rule_unit and computed_unit and rule_unit != computed_unit:
            return {
                "status": "unresolved",
                "reason": "Расчетная единица фасовки не совпадает с единицей в «Справочник фасовок».",
            }
        if rule_factor is not None and computed_multiplier is not None and not _numbers_equal(
            rule_factor,
            computed_multiplier,
        ):
            return {
                "status": "unresolved",
                "reason": "Расчетный коэффициент не совпадает с сохраненным коэффициентом фасовки.",
                "stored_conversion_factor": rule_factor,
            }
        if computed_multiplier is not None:
            return {
                "status": "resolved",
                "multiplier": computed_multiplier,
                "accounting_unit": rule_unit or computed_unit,
                "method": computed_method,
                "rule_id": rule_id,
            }
        if rule_factor is not None:
            return {
                "status": "resolved",
                "multiplier": rule_factor,
                "accounting_unit": rule_unit or document_unit,
                "method": "package_reference",
                "rule_id": rule_id,
            }
        return {"status": "unresolved", "reason": "Правило пересчета не содержит коэффициента."}

    # No matching rule at all.
    if computed_method in {"identity", "identity_document_unit"}:
        return {
            "status": "resolved",
            "multiplier": computed_multiplier,
            "accounting_unit": computed_unit,
            "method": computed_method,
            "rule_id": None,
        }
    if _package_raw(item):
        return {
            "status": "no_rule",
            "reason": "Фасовка не найдена в справочнике «Справочник фасовок» — количество оставлено без пересчета.",
            "multiplier": 1.0,
            "accounting_unit": document_unit,
            "method": "identity_no_rule",
            "rule_id": None,
        }
    if computed_method == "unresolved":
        return {"status": "unresolved", "reason": "Не удалось уверенно определить фасовку или единицу учета."}
    return {
        "status": "resolved",
        "multiplier": computed_multiplier,
        "accounting_unit": computed_unit,
        "method": computed_method,
        "rule_id": None,
    }


def _rule_activity_state(rule: dict[str, Any]) -> str:
    """3-state rule activity (`Правила фасовок`'s `Активность правила`), kept
    backward compatible with the legacy boolean-ish `Активна` column (which
    only ever yields active/inactive, never review)."""
    raw = _catalog_value(rule, "Активность правила", "Активна", "active")
    text = str(raw or "").strip().lower().replace("ё", "е")
    if text in {"неактивно", "нет", "false", "0", "inactive"}:
        return _RULE_INACTIVE
    if text in {"требует проверки", "проверка", "review"}:
        return _RULE_NEEDS_REVIEW
    if text in {"активно", "да", "true", "1", "active", ""}:
        return _RULE_ACTIVE
    return _RULE_NEEDS_REVIEW  # unknown value -> safe default, never auto-applied


def _match_conversion_rule(
    item: dict[str, Any],
    product_match: dict[str, Any],
    rules: list[dict[str, Any]],
    *,
    document_unit: str,
    warehouse: str | None = None,
    supplier_inn: str | None = None,
    supplier_name: str | None = None,
) -> dict[str, Any]:
    """Find the active rule that applies to this item.

    Matching is specificity-tiered: a rule that names the УС product code,
    warehouse/destination, supplier INN, or supplier product code is more
    specific than one matched only by product name or package text. A rule
    that *specifies* a constraint the item fails is disqualified outright
    (not merely un-scored) -- this is what makes "most specific wins" safe,
    e.g. a warehouse-scoped rule must not apply to a document from a
    different warehouse just because the product code also matched. Only
    when more than one rule remains at the single highest specificity tier
    (after a `Приоритет правила` tiebreak) is the result "ambiguous",
    forcing manual review instead of an automatic pick.
    """
    package_raw = _normalize_compact(_package_raw(item))
    raw_name = _normalize_name(item.get("raw_name") or item.get("name"))
    item_names = {
        _normalize_name(item.get("normalized_name_candidate")),
        _normalize_name(item.get("clean_name")),
        _normalize_name(product_match.get("name")),
    }
    item_names.discard("")
    product_code = str(product_match.get("code") or "").strip()
    supplier_codes = {str(code).strip() for code in (item.get("codes") or []) if str(code).strip()}
    doc_warehouse = _normalize_name(warehouse)
    doc_supplier_inn = str(supplier_inn or "").strip()
    doc_supplier_name = _normalize_name(supplier_name)

    candidates: list[dict[str, Any]] = []
    for rule in rules:
        if _rule_activity_state(rule) != _RULE_ACTIVE:
            continue

        rule_document_unit = _normalize_unit(
            _catalog_value(
                rule, "Ед.изм. в документе", "Ед. изм. документа", "Единица документа", "document_unit"
            )
        )
        if rule_document_unit and rule_document_unit != document_unit:
            continue

        package_variants = {
            _normalize_compact(value)
            for value in (
                _catalog_value(rule, "Фасовка в документе", "Состав упаковки", "document_package"),
                _catalog_value(rule, "Основная фасовка", "primary_package"),
                *str(_catalog_value(rule, "Варианты", "variants") or "").split(";"),
            )
            if value
        }
        package_hit = bool(package_raw) and package_raw in package_variants

        rule_product_name = _normalize_name(
            _catalog_value(
                rule, "Наименование товара в УС", "Наименование товара УС", "Наименование товара", "Товар", "product_name"
            )
        )
        # `Код товара УС` (matched product's catalog code) and `Код товара
        # поставщика` (supplier-side code extracted from the raw text) are
        # distinct vocabularies on the new sheet -- compared separately
        # against separate item fields, not conflated into one lookup.
        rule_us_code = str(_catalog_value(rule, "Код товара УС", "product_code") or "").strip()
        rule_supplier_code = str(
            _catalog_value(rule, "Код товара поставщика", "supplier_product_code") or ""
        ).strip()
        product_hit = bool(rule_product_name) and rule_product_name in item_names
        us_code_hit = bool(rule_us_code) and bool(product_code) and rule_us_code == product_code
        supplier_code_hit = bool(rule_supplier_code) and rule_supplier_code in supplier_codes

        if not (package_hit or product_hit or us_code_hit or supplier_code_hit):
            continue

        qualifier = _normalize_name(_catalog_value(rule, "Вариант", "Квалификатор", "qualifier"))
        if qualifier and qualifier not in raw_name:
            continue

        score = 0
        disqualified = False

        if rule_us_code:
            if us_code_hit:
                score += 100
            else:
                disqualified = True
        rule_warehouse = _normalize_name(
            _catalog_value(rule, "Склад / назначение", "Склад/назначение", "warehouse")
        )
        if rule_warehouse:
            if doc_warehouse and rule_warehouse == doc_warehouse:
                score += 40
            else:
                disqualified = True
        rule_supplier_inn = str(_catalog_value(rule, "ИНН поставщика", "supplier_inn") or "").strip()
        if rule_supplier_inn:
            if doc_supplier_inn and rule_supplier_inn == doc_supplier_inn:
                score += 20
            else:
                disqualified = True
        if rule_supplier_code:
            if supplier_code_hit:
                score += 30
            else:
                disqualified = True
        rule_supplier_name = _normalize_name(_catalog_value(rule, "Поставщик", "supplier_name"))
        if rule_supplier_name:
            if doc_supplier_name and rule_supplier_name == doc_supplier_name:
                score += 10
            else:
                disqualified = True
        if disqualified:
            continue
        if product_hit:
            score += 5
        if package_hit:
            score += 3

        # A rule matched purely by package text is a physical packaging fact
        # and can be sanity-checked against the regex-computed conversion.
        # A rule matched by product identity (weight-exception style, e.g.
        # eggs/avocado/olives) overrides the computed guess outright, since
        # the computed value for such items is usually a meaningless identity
        # default rather than a real package decomposition candidate.
        match_kind = "product" if (us_code_hit or product_hit or supplier_code_hit) else "package"
        priority = _number(_catalog_value(rule, "Приоритет правила", "Приоритет", "priority"))
        candidates.append(
            {
                "rule": rule,
                "match_kind": match_kind,
                "score": score,
                "priority": priority if priority is not None else float("inf"),
            }
        )

    if not candidates:
        return {"status": "missing"}

    top_score = max(candidate["score"] for candidate in candidates)
    top_tier = [candidate for candidate in candidates if candidate["score"] == top_score]
    if len(top_tier) > 1:
        best_priority = min(candidate["priority"] for candidate in top_tier)
        top_tier = [candidate for candidate in top_tier if candidate["priority"] == best_priority]
    if len(top_tier) > 1:
        return {"status": "ambiguous"}
    return {"status": "matched", "rule": top_tier[0]["rule"], "match_kind": top_tier[0]["match_kind"]}


def _dry_weight_multiplier(item: dict[str, Any]) -> tuple[float | None, str]:
    package = item.get("package") if isinstance(item.get("package"), dict) else {}
    value = _number(package.get("dry_weight"))
    unit = _normalize_unit(package.get("dry_weight_unit") or package.get("unit"))
    return _convert_package_value(value, unit)


def _normalize_method_label(value: Any) -> str:
    text = str(value or "").strip().lower().replace("ё", "е")
    return re.sub(r"\s+", " ", text)


def _positive_number(value: Any) -> float | None:
    number = _number(value)
    if number is None or number <= 0:
        return None
    return number


def _apply_units_per_package(multiplier: float | None, units_per_package: float | None) -> float | None:
    if multiplier is None:
        return None
    if units_per_package is None:
        return multiplier
    return _multiply(multiplier, units_per_package)


def _package_method(method: str, units_per_package: float | None) -> str:
    if units_per_package is None or units_per_package == 1:
        return method
    return f"{method}_with_units_per_package"


def _extract_package(raw_name: str) -> tuple[InvoiceItemPackage, float | None, str]:
    dimension = _DIMENSION_RE.search(raw_name)
    if dimension:
        return (
            InvoiceItemPackage(value=None, unit="см", raw=_clean_spaces(dimension.group(0))),
            None,
            "",
        )

    compound = _COMPOUND_PACKAGE_RE.search(raw_name)
    if compound:
        count = _number(compound.group("count"))
        value = _number(compound.group("value"))
        unit = _normalize_unit(compound.group("unit"))
        base_multiplier, accounting_unit = _convert_package_value(value, unit)
        return (
            InvoiceItemPackage(value=value, unit=unit, raw=_clean_spaces(compound.group(0))),
            _multiply(count, base_multiplier),
            accounting_unit,
        )

    matches = list(_PACKAGE_RE.finditer(raw_name))
    if not matches:
        return InvoiceItemPackage(), None, ""

    primary = matches[0]
    value = _number(primary.group("value"))
    unit = _normalize_unit(primary.group("unit"))
    multiplier, accounting_unit = _convert_package_value(value, unit)
    if len(matches) > 1 and unit in {"г", "кг", "мл", "л"}:
        count_match = next(
            (match for match in matches[1:] if _normalize_unit(match.group("unit")) in {"шт", "пак"}),
            None,
        )
        if count_match:
            multiplier = _multiply(multiplier, _number(count_match.group("value")))
    return (
        InvoiceItemPackage(value=value, unit=unit, raw=_clean_spaces(primary.group(0))),
        multiplier,
        accounting_unit,
    )


_PACKAGE_VALUE_FACT_TYPES = {"unit_weight", "unit_volume", "declared_package_mass", "capacity"}


def _package_from_facts(facts: list[PackagingFact]) -> InvoiceItemPackage:
    """Backend-only compatibility view: derive a legacy InvoiceItemPackage from AI-supplied
    packaging_facts, used only when regex extraction from raw_name found nothing."""
    value_fact = next((fact for fact in facts if fact.type in _PACKAGE_VALUE_FACT_TYPES), None)
    dry_weight_fact = next((fact for fact in facts if fact.type == "dry_weight"), None)
    return InvoiceItemPackage(
        value=_number(value_fact.value) if value_fact else None,
        unit=(_normalize_unit(value_fact.unit) or None) if value_fact else None,
        raw=_clean_spaces(value_fact.source) if value_fact else "",
        dry_weight=_number(dry_weight_fact.value) if dry_weight_fact else None,
        dry_weight_unit=(_normalize_unit(dry_weight_fact.unit) or None) if dry_weight_fact else None,
    )


def _units_per_package_from_facts(facts: list[PackagingFact]) -> float | None:
    count_fact = next((fact for fact in facts if fact.type == "count_in_package"), None)
    return _number(count_fact.value) if count_fact else None


def _fallback_multiplier(package: InvoiceItemPackage, document_unit: str) -> tuple[float | None, str]:
    multiplier, accounting_unit = _convert_package_value(_number(package.value), _normalize_unit(package.unit))
    if multiplier is not None:
        return multiplier, accounting_unit
    normalized_document_unit = _normalize_unit(document_unit)
    if normalized_document_unit in {"кг", "л", "шт", "бут"}:
        return 1.0, normalized_document_unit
    return None, ""


def _convert_package_value(value: float | None, unit: str) -> tuple[float | None, str]:
    if value is None:
        return None, ""
    if unit == "г":
        return value / 1000, "кг"
    if unit == "кг":
        return value, "кг"
    if unit == "мл":
        return value / 1000, "л"
    if unit == "л":
        return value, "л"
    if unit in {"шт", "пак", "бут"}:
        return value, "шт" if unit == "шт" else unit
    return None, ""


def _clean_product_name(value: Any, package_raw: str = "") -> str:
    text = _clean_spaces(value)
    if not text:
        return ""
    text = _CODE_RE.sub(" ", text)
    text = re.sub(r"\[[^\]]*\]", " ", text)
    text = re.sub(r"^\s*\d+(?=[A-ZА-ЯЁ])", "", text, flags=re.IGNORECASE)
    text = _TECHNICAL_PREFIX_RE.sub("", text)
    if package_raw:
        text = re.sub(re.escape(package_raw), " ", text, flags=re.IGNORECASE)
    if _PROMO_PACKAGING_TOKEN_RE.search(text):
        original_text = text
        reduced = _PROMO_PACKAGING_TOKEN_RE.sub(" ", text)
        reduced = re.sub(r"\b\d+(?:[.,]\d+)?\s*[*XХ]\s*\d+(?:[.,]\d+)?\s*СМ\b", " ", reduced, flags=re.IGNORECASE)
        reduced = re.sub(r"\s+", " ", reduced).strip()
        if reduced and len(reduced) >= 4:
            text = reduced
        elif re.search(r"\bПАКЕТ\b", original_text, re.IGNORECASE):
            text = "ПАКЕТ"
    text = re.sub(r"^[\[\]():;,.+\-\s]+|[\[\]():;,+\s]+$", "", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _readable_name(value: str) -> str:
    if not value:
        return ""
    words = []
    for word in value.split():
        words.append(word if re.search(r"\d", word) else word.capitalize())
    return " ".join(words)


def _match_product(item: dict[str, Any], products: list[dict[str, Any]]) -> dict[str, Any]:
    query = (
        item.get("normalized_name_candidate")
        or item.get("clean_name")
        or item.get("name")
        or item.get("raw_name")
        or ""
    )
    ranked = []
    for product in products:
        name = _catalog_value(product, "Наименование", "name")
        if not name:
            continue
        ranked.append((_name_similarity(query, name), name, product))
    ranked.sort(key=lambda candidate: candidate[0], reverse=True)
    if not ranked or ranked[0][0] < 0.62:
        return {"status": "missing"}
    best_score, best_name, best = ranked[0]
    second_score = ranked[1][0] if len(ranked) > 1 else 0
    if best_score < 0.82 or second_score >= best_score - 0.04:
        return {"status": "ambiguous", "name": best_name, "score": best_score}
    return {
        "status": "matched",
        "name": best_name,
        "code": _catalog_value(best, "Код", "code"),
        "unit": _normalize_unit(_catalog_value(best, "Ед. изм.", "unit")),
        "score": best_score,
    }


def _add_mapping_problem(
    item: dict[str, Any],
    line_number: int,
    field: str,
    reason: str,
    correction: str,
    review_flags: list[dict[str, Any]],
    corrections: dict[Any, str],
    parser_notes: list[str],
) -> None:
    if not item.get("correction"):
        item["correction"] = correction
    item["needs_review"] = True
    item["review_reason"] = item.get("review_reason") or reason
    flag = {
        "scope": "item",
        "line_number": line_number,
        "field": field,
        "reason": reason,
        "severity": "warning",
    }
    if flag not in review_flags:
        review_flags.append(flag)
    corrections[line_number] = item["correction"]
    if reason not in parser_notes:
        parser_notes.append(reason)


def _name_similarity(left: Any, right: Any) -> float:
    left_normalized = _normalize_name(left)
    right_normalized = _normalize_name(right)
    if not left_normalized or not right_normalized:
        return 0.0
    if left_normalized == right_normalized:
        return 1.0
    if left_normalized in right_normalized or right_normalized in left_normalized:
        shorter = min(len(left_normalized), len(right_normalized))
        longer = max(len(left_normalized), len(right_normalized))
        return max(0.84, shorter / longer)
    left_tokens = set(left_normalized.split())
    right_tokens = set(right_normalized.split())
    token_score = len(left_tokens & right_tokens) / max(len(left_tokens | right_tokens), 1)
    return max(SequenceMatcher(None, left_normalized, right_normalized).ratio(), token_score)


def _normalize_name(value: Any) -> str:
    text = str(value or "").lower().replace("ё", "е")
    text = re.sub(r"[^a-zа-я0-9%]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _normalize_compact(value: Any) -> str:
    return re.sub(r"[\s.,]+", "", str(value or "").lower().replace("x", "х"))


def _normalize_document_unit(value: Any) -> str:
    normalized = _normalize_unit(value)
    return normalized.upper() if normalized else ""


def _normalize_unit(value: Any) -> str:
    text = _clean_spaces(value).upper()
    return _UNIT_ALIASES.get(text, text.lower())


def _package_raw(item: dict[str, Any]) -> str:
    package = item.get("package") or {}
    return _clean_spaces(package.get("raw") if isinstance(package, dict) else "")


def _catalog_value(row: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        if row.get(key) not in (None, ""):
            return row[key]
    return None


def _fallback_us_product_name(item: dict[str, Any]) -> str:
    for key in ("normalized_name_candidate", "clean_name", "name", "raw_name"):
        value = _clean_spaces(item.get(key))
        if value:
            return value
    return ""


def _number(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(Decimal(str(value).replace(" ", "").replace(",", ".")))
    except (InvalidOperation, ValueError):
        return None


def _multiply(left: Any, right: Any) -> float | None:
    left_number = _decimal(left)
    right_number = _decimal(right)
    if left_number is None or right_number is None:
        return None
    return float(round(left_number * right_number, 6))


def _divide(left: Any, right: Any) -> float | None:
    left_number = _decimal(left)
    right_number = _decimal(right)
    if left_number is None or right_number is None or right_number <= 0:
        return None
    return float(round(left_number / right_number, 6))


def _conversion_amount_delta(
    quantity_document: Any,
    price_document: Any,
    quantity_us: Any,
    price_us: Any,
) -> float | None:
    values = [
        _decimal(quantity_document),
        _decimal(price_document),
        _decimal(quantity_us),
        _decimal(price_us),
    ]
    if any(value is None for value in values):
        return None
    quantity_doc, price_doc, quantity_accounting, price_accounting = values
    delta = abs(
        (quantity_doc * price_doc)
        - (quantity_accounting * price_accounting)
    )
    return float(round(delta, 6))


def _numbers_equal(left: Any, right: Any, tolerance: str = "0.000001") -> bool:
    left_number = _decimal(left)
    right_number = _decimal(right)
    if left_number is None or right_number is None:
        return False
    return abs(left_number - right_number) <= Decimal(tolerance)


def _decimal(value: Any) -> Decimal | None:
    if value in (None, ""):
        return None
    try:
        return Decimal(str(value).replace(" ", "").replace(",", "."))
    except (InvalidOperation, ValueError):
        return None


def _clean_spaces(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _deduplicate(values: list[str]) -> list[str]:
    result = []
    for value in values:
        normalized = _clean_spaces(value)
        if normalized and normalized not in result:
            result.append(normalized)
    return result


def _issue(field: str, reason: str) -> dict[str, str]:
    return {"field": field, "reason": reason, "severity": "warning"}


def _deduplicate_issues(issues: list[dict[str, str]]) -> list[dict[str, str]]:
    result = []
    for issue in issues:
        if issue not in result:
            result.append(issue)
    return result
