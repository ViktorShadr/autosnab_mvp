"""iiko reference synchronization and automatic invoice field mapping.

This module fills technical iiko fields for MVP-4 automatically when real iiko
credentials are configured. If iiko is not configured, it keeps the user-facing
invoice data and marks missing technical fields for review instead of pretending
that mapping succeeded.
"""

from __future__ import annotations

import json
import re
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from app.config import settings
from app.services.iiko_incoming_invoice_service import IikoConfigurationError, IikoRequestError

_CACHE_TTL_SECONDS = 300
_CACHE: dict[str, Any] = {"loaded_at": 0, "context": None, "error": None}


@dataclass
class MatchResult:
    value: str | None
    name: str | None
    confidence: float
    status: str
    reason: str
    extra: dict[str, Any]


def auto_fill_iiko_fields(header: dict[str, Any], items: list[dict[str, Any]], *, supplier_name: str | None, venue: str | None) -> dict[str, Any]:
    """Return header/items enriched with iiko ids/articles/units/tax fields.

    The function is safe for local MVP runs: if iiko is disabled or unavailable,
    it leaves the original values and writes mapping statuses/errors so the
    user sees what still needs attention in Google Sheets.
    """
    enriched_header = dict(header or {})
    enriched_items = [dict(item) for item in items]
    notes: list[str] = []

    context_result = get_iiko_reference_context()
    context = context_result.get("context") or {}
    if context_result.get("status") != "ready":
        message = context_result.get("message") or "Справочники iiko недоступны; технические поля требуют проверки"
        notes.append(message)
        header_missing = []
        if not enriched_header.get("iiko_supplier_id"):
            header_missing.append("не заполнен iiko_supplier_id")
        if not enriched_header.get("iiko_default_store_id"):
            header_missing.append("не заполнен iiko_default_store_id/defaultStore")
        enriched_header["iiko_mapping_status"] = "ready" if not header_missing else "needs_review"
        enriched_header["iiko_mapping_error"] = "; ".join(header_missing) if header_missing else ""
        for item in enriched_items:
            if item.get("iiko_product_id") or item.get("product_article"):
                item.setdefault("mapping_status", "ready")
                item.setdefault("amount_unit", item.get("amount_unit") or item.get("unit") or "шт")
            else:
                _mark_item_if_missing(item, "needs_review", message)
        return {"header": enriched_header, "items": enriched_items, "notes": notes, "context_status": context_result.get("status")}

    supplier_match = _match_supplier(supplier_name, context.get("suppliers", []))
    if not enriched_header.get("iiko_supplier_id") and supplier_match.value:
        enriched_header["iiko_supplier_id"] = supplier_match.value
    enriched_header["iiko_supplier_name"] = supplier_match.name or supplier_name
    enriched_header["iiko_supplier_match_confidence"] = supplier_match.confidence

    store_match = _match_store(
        enriched_header.get("iiko_default_store_id") or enriched_header.get("iiko_organization") or venue,
        context.get("stores", []),
    )
    if not enriched_header.get("iiko_default_store_id") and store_match.value:
        enriched_header["iiko_default_store_id"] = store_match.value
    enriched_header["iiko_default_store_name"] = store_match.name or enriched_header.get("iiko_default_store_id")
    enriched_header["iiko_default_store_match_confidence"] = store_match.confidence

    header_errors = []
    if not enriched_header.get("iiko_supplier_id"):
        header_errors.append(supplier_match.reason)
    if not enriched_header.get("iiko_default_store_id"):
        header_errors.append(store_match.reason)
    enriched_header["iiko_mapping_status"] = "ready" if not header_errors else "needs_review"
    enriched_header["iiko_mapping_error"] = "; ".join(err for err in header_errors if err)

    for item in enriched_items:
        _auto_fill_item(item, enriched_header, context)

    return {"header": enriched_header, "items": enriched_items, "notes": notes, "context_status": "ready"}


def get_iiko_reference_context(force_refresh: bool = False) -> dict[str, Any]:
    """Load iiko reference context: suppliers, products, stores, units, taxes."""
    if not settings.iiko_integration_enabled:
        return {"status": "disabled", "message": "IIKO_INTEGRATION_ENABLED=false; автосопоставление со справочниками iiko отключено"}
    if not settings.iiko_base_url:
        return {"status": "not_configured", "message": "Не указан IIKO_BASE_URL"}

    now = time.time()
    if not force_refresh and _CACHE["context"] is not None and now - _CACHE["loaded_at"] < _CACHE_TTL_SECONDS:
        return {"status": "ready", "context": _CACHE["context"], "cached": True}

    try:
        token = settings.iiko_token or _authorize()
        context = {
            "suppliers": _normalize_entities(_request_iiko("/resto/api/suppliers", token), kind="supplier"),
            "products": _normalize_entities(_request_iiko("/resto/api/v2/entities/products/list", token, {"includeDeleted": "false"}), kind="product"),
            "stores": _normalize_entities(_request_iiko("/resto/api/v2/entities/list", token, {"rootType": "Account", "includeDeleted": "false"}), kind="store"),
            "units": _normalize_entities(_request_iiko("/resto/api/v2/entities/list", token, {"rootType": "MeasureUnit", "includeDeleted": "false"}), kind="unit"),
            "taxes": _normalize_entities(_request_iiko("/resto/api/v2/entities/list", token, {"rootType": "TaxCategory", "includeDeleted": "false"}), kind="tax"),
        }
        _CACHE.update({"loaded_at": now, "context": context, "error": None})
        return {"status": "ready", "context": context, "cached": False}
    except Exception as exc:  # noqa: BLE001 - external iiko errors must be visible in Sheets
        _CACHE.update({"loaded_at": now, "context": None, "error": str(exc)})
        return {"status": "error", "message": f"Не удалось загрузить справочники iiko: {exc}"}


def invalidate_iiko_reference_cache() -> None:
    _CACHE.update({"loaded_at": 0, "context": None, "error": None})


def _auto_fill_item(item: dict[str, Any], header: dict[str, Any], context: dict[str, Any]) -> None:
    item_name = item.get("name") or ""
    product_match = _match_product(item_name, context.get("products", []))
    if not item.get("iiko_product_id") and product_match.value:
        item["iiko_product_id"] = product_match.value
    if not item.get("product_article"):
        article = product_match.extra.get("num") or product_match.extra.get("code")
        if article:
            item["product_article"] = article
    item["iiko_product_name"] = product_match.name or item_name
    item["iiko_product_match_confidence"] = product_match.confidence

    unit_match = _match_unit(item.get("unit") or item.get("amount_unit"), context.get("units", []))
    if not item.get("amount_unit"):
        item["amount_unit"] = unit_match.value or unit_match.name or item.get("unit") or "шт"
    item["iiko_unit_name"] = unit_match.name or item.get("unit")
    item["iiko_unit_match_confidence"] = unit_match.confidence

    if not item.get("store_id") and header.get("iiko_default_store_id"):
        item["store_id"] = header["iiko_default_store_id"]

    if item.get("vat_percent") is None:
        tax_percent = _tax_percent_from_product(product_match.extra, context.get("taxes", []))
        if tax_percent is not None:
            item["vat_percent"] = tax_percent
    if item.get("vat_sum") is None and item.get("vat_percent") is not None:
        try:
            item_sum = float(item.get("sum") if item.get("sum") is not None else float(item.get("quantity") or 0) * float(item.get("price") or 0))
            vat_percent = float(item.get("vat_percent") or 0)
            item["vat_sum"] = round(item_sum * vat_percent / (100 + vat_percent), 2) if vat_percent > 0 else 0
        except (TypeError, ValueError):
            pass

    errors = []
    if not (item.get("iiko_product_id") or item.get("product_article")):
        errors.append(product_match.reason)
    if not item.get("amount_unit"):
        errors.append(unit_match.reason)
    if not item.get("store_id"):
        errors.append("не определен склад/defaultStore для позиции")
    item["mapping_status"] = "ready" if not errors else "needs_review"
    item["mapping_error"] = "; ".join(err for err in errors if err)


def _mark_item_if_missing(item: dict[str, Any], status: str, message: str) -> None:
    item.setdefault("amount_unit", item.get("unit") or "шт")
    item.setdefault("mapping_status", status)
    if not (item.get("iiko_product_id") or item.get("product_article")):
        item.setdefault("mapping_error", message)


def _match_supplier(name: str | None, suppliers: list[dict[str, Any]]) -> MatchResult:
    return _best_match(name, suppliers, ["name", "legalName", "code", "taxpayerIdNumber"], "поставщик iiko не найден")


def _match_store(name: str | None, stores: list[dict[str, Any]]) -> MatchResult:
    if not name and len(stores) == 1:
        store = stores[0]
        return MatchResult(store.get("id"), store.get("name"), 0.6, "auto_single", "выбран единственный склад iiko", store)
    return _best_match(name, stores, ["name", "code"], "склад/defaultStore iiko не найден")


def _match_product(name: str | None, products: list[dict[str, Any]]) -> MatchResult:
    return _best_match(name, products, ["name", "num", "code", "description"], "товар iiko не найден")


def _match_unit(name: str | None, units: list[dict[str, Any]]) -> MatchResult:
    if not units and name:
        return MatchResult(str(name), str(name), 0.4, "fallback", "единицы iiko недоступны; оставлена OCR-единица", {})
    return _best_match(name, units, ["name", "code", "shortName"], "единица измерения iiko не найдена")


def _best_match(query: str | None, entities: list[dict[str, Any]], fields: list[str], not_found_reason: str) -> MatchResult:
    query_norm = _normalize_text(query)
    if not query_norm:
        return MatchResult(None, None, 0.0, "needs_review", not_found_reason, {})
    best_entity = None
    best_score = 0.0
    for entity in entities:
        for field in fields:
            value = entity.get(field)
            score = _similarity(query_norm, _normalize_text(value))
            if score > best_score:
                best_score = score
                best_entity = entity
    if best_entity and best_score >= 0.72:
        return MatchResult(best_entity.get("id") or best_entity.get("code") or best_entity.get("num"), best_entity.get("name"), best_score, "ready", "сопоставлено автоматически", best_entity)
    if best_entity and best_score >= 0.55:
        return MatchResult(best_entity.get("id") or best_entity.get("code") or best_entity.get("num"), best_entity.get("name"), best_score, "needs_review", "низкая уверенность автоматического сопоставления", best_entity)
    return MatchResult(None, best_entity.get("name") if best_entity else None, best_score, "needs_review", not_found_reason, best_entity or {})


def _similarity(left: str, right: str) -> float:
    if not left or not right:
        return 0.0
    if left == right:
        return 1.0
    if left in right or right in left:
        shorter = min(len(left), len(right))
        longer = max(len(left), len(right))
        return max(0.75, shorter / longer)
    return SequenceMatcher(None, left, right).ratio()


def _normalize_text(value: Any) -> str:
    if value is None:
        return ""
    text = str(value).lower().replace("ё", "е")
    text = re.sub(r"[^a-zа-я0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _tax_percent_from_product(product: dict[str, Any], taxes: list[dict[str, Any]]) -> float | None:
    tax_id = product.get("taxCategory") or product.get("tax_category")
    if not tax_id:
        return None
    for tax in taxes:
        if str(tax.get("id")) == str(tax_id):
            value = tax.get("vatPercent") or tax.get("percent") or tax.get("taxPercent")
            try:
                return float(value) if value is not None else None
            except (TypeError, ValueError):
                return None
    return None


def _authorize() -> str:
    if settings.iiko_token:
        return settings.iiko_token
    if not settings.iiko_login or not settings.iiko_password_sha1:
        raise IikoConfigurationError("Для загрузки справочников iiko нужны IIKO_LOGIN и IIKO_PASSWORD_SHA1 или IIKO_TOKEN")
    url = f"{settings.iiko_base_url.rstrip('/')}/resto/api/auth?{urlencode({'login': settings.iiko_login, 'pass': settings.iiko_password_sha1})}"
    try:
        with urlopen(url, timeout=settings.iiko_timeout_seconds) as response:  # noqa: S310 - configured iiko host
            return response.read().decode("utf-8", errors="replace").strip()
    except HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise IikoRequestError(f"iiko auth HTTP {exc.code}: {body}") from exc
    except URLError as exc:
        raise IikoRequestError(f"Ошибка авторизации iiko: {exc.reason}") from exc


def _request_iiko(path: str, token: str, params: dict[str, str] | None = None) -> Any:
    query = {"key": token}
    if params:
        query.update(params)
    url = f"{settings.iiko_base_url.rstrip('/')}{path}?{urlencode(query)}"
    request = Request(url, method="GET")
    try:
        with urlopen(request, timeout=settings.iiko_timeout_seconds) as response:  # noqa: S310 - configured iiko host
            body = response.read().decode("utf-8", errors="replace")
            return _parse_body(body)
    except HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise IikoRequestError(f"iiko HTTP {exc.code} for {path}: {body}") from exc
    except URLError as exc:
        raise IikoRequestError(f"Ошибка соединения с iiko для {path}: {exc.reason}") from exc


def _parse_body(body: str) -> Any:
    body = body.strip()
    if not body:
        return []
    try:
        return json.loads(body)
    except json.JSONDecodeError:
        return _xml_to_entities(body)


def _xml_to_entities(body: str) -> list[dict[str, Any]]:
    try:
        root = ET.fromstring(body)
    except ET.ParseError:
        return []
    result = []
    for element in root.iter():
        children = list(element)
        if not children:
            continue
        entity = {child.tag.split("}", 1)[-1]: child.text for child in children if child.text is not None}
        if entity.get("id") or entity.get("name") or entity.get("code"):
            result.append(entity)
    return result


def _normalize_entities(data: Any, kind: str) -> list[dict[str, Any]]:
    raw_items = data if isinstance(data, list) else data.get("items", []) if isinstance(data, dict) else []
    entities = []
    for raw in raw_items:
        if not isinstance(raw, dict):
            continue
        entity = dict(raw)
        entity["kind"] = kind
        if "name" not in entity:
            entity["name"] = entity.get("displayName") or entity.get("legalName") or entity.get("fullName") or entity.get("code")
        entities.append(entity)
    return entities
