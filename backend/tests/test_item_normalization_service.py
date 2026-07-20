"""Regression tests for Lilia's 2026-07-20 Метро.pdf feedback.

Each test below encodes one of the seven line items Lilia reported as wrongly
recalculated (`Кол-во в УС`). Five of them (napkins, water, trash bags,
straws, and the "no rule found" case in general) are fixed purely by the
corrected default: without a matching active `Справочник фасовок` /
`Правила пересчета` row, the accounting quantity no longer gets silently
decomposed from a regex-recognized package pattern. Toilet paper and olives
need an explicit rule row (`По количеству вложений` / `По сухому весу`)
because the correct answer genuinely requires recalculation. Chips is kept
deliberately ambiguous, demonstrating that the *rule* decides the method, not
the parser.
"""

from app.services.item_normalization_service import apply_reference_mapping_to_payload


def _payload(item: dict) -> dict:
    return {
        "items": [{"line_number": 1, **item}],
        "parser_metadata": {
            "upload_status": "Проверить",
            "row_status": "Распознано",
            "review_flags": [],
            "item_corrections": {},
        },
        "parser_notes": [],
    }


def test_napkins_stay_as_packs_without_a_rule():
    # "Салфетки 250 шт в пачке, всего 3 пач (ШТ)" -> должно остаться 3, не 750.
    payload = _payload(
        {
            "name": "САЛФЕТКИ БУМАЖНЫЕ 250ШТ",
            "raw_name": "САЛФЕТКИ БУМАЖНЫЕ 250ШТ",
            "package": {"value": 250, "unit": "шт", "raw": "250ШТ"},
            "document_unit": "ШТ",
            "quantity": 3,
            "quantity_document": 3,
            "price": 45.0,
        }
    )

    result = apply_reference_mapping_to_payload(payload, products=[], packages=[])
    item = result["items"][0]

    assert item["conversion_method"] == "identity_no_rule"
    assert item["quantity_us"] == 3


def test_toilet_paper_needs_an_explicit_units_per_package_rule():
    # "12 рул в упаковке, упаковок 2" -> должно быть 2 * 12 = 24, а не 2.
    payload = _payload(
        {
            "name": "ТУАЛЕТНАЯ БУМАГА 12РУЛ",
            "raw_name": "ТУАЛЕТНАЯ БУМАГА 12РУЛ",
            "package": {"value": 12, "unit": "шт", "raw": "12РУЛ"},
            "document_unit": "УП",
            "quantity": 2,
            "quantity_document": 2,
            "price": 480.0,
        }
    )

    without_rule = apply_reference_mapping_to_payload(payload, products=[], packages=[])
    assert without_rule["items"][0]["quantity_us"] == 2  # no rule yet -> safe default, not a silent guess

    with_rule = apply_reference_mapping_to_payload(
        payload,
        products=[],
        packages=[
            {
                "ID": "toilet-paper-12",
                "Фасовка в документе": "12РУЛ",
                "Способ пересчета": "По количеству вложений",
                "Коэффициент пересчета": 12,
                "Единица учета в УС": "рул",
                "Активна": "да",
            }
        ],
    )
    item = with_rule["items"][0]
    assert item["conversion_method"] == "package_units_rule"
    assert item["quantity_us"] == 24
    assert item["us_unit"] == "рул"


def test_olives_use_dry_weight_rule_not_gross_weight():
    # "Оливки ... должны записываться в кол-во УС в сухом весе без рассола".
    payload = _payload(
        {
            "name": "МАСЛИНЫ Б/К 300Г/150Г ОТЖ.ВЕС",
            "raw_name": "МАСЛИНЫ Б/К 300Г/150Г ОТЖ.ВЕС",
            "normalized_name_candidate": "Маслины Б/К",
            "package": {"value": 300, "unit": "г", "raw": "300Г", "dry_weight": 150, "dry_weight_unit": "г"},
            "document_unit": "ШТ",
            "quantity": 2,
            "quantity_document": 2,
            "price": 120.0,
        }
    )

    result = apply_reference_mapping_to_payload(
        payload,
        products=[{"Наименование": "Маслины Б/К", "Ед. изм.": "кг"}],
        packages=[
            {
                "ID": "olives-dry-weight",
                "Наименование товара УС": "Маслины Б/К",
                "Способ пересчета": "По сухому весу",
                "Единица учета в УС": "кг",
                "Активна": "да",
            }
        ],
    )
    item = result["items"][0]

    assert item["conversion_method"] == "dry_weight_rule"
    assert item["quantity_us"] == 0.3  # 2 * (150г -> 0.15кг)
    assert item["us_unit"] == "кг"


def test_bottled_water_stays_in_bottles_without_a_rule():
    # "0,5 л Вода ... надо в бутылях и оприходовать без пересчета 24 бут".
    payload = _payload(
        {
            "name": "ВОДА ПИТЬЕВАЯ НЕГАЗ 0,5Л",
            "raw_name": "ВОДА ПИТЬЕВАЯ НЕГАЗ 0,5Л",
            "package": {"value": 0.5, "unit": "л", "raw": "0,5Л"},
            "document_unit": "БУТ",
            "quantity": 24,
            "quantity_document": 24,
            "price": 25.0,
        }
    )

    result = apply_reference_mapping_to_payload(payload, products=[], packages=[])
    item = result["items"][0]

    assert item["conversion_method"] == "identity_no_rule"
    assert item["quantity_us"] == 24


def test_trash_bag_rolls_stay_as_rolls_without_a_rule():
    # "10 шт Мешки для мусора пришли 6 шт ... надо 6, а не 60".
    payload = _payload(
        {
            "name": "МЕШКИ ДЛЯ МУСОРА 10ШТ",
            "raw_name": "МЕШКИ ДЛЯ МУСОРА 10ШТ",
            "package": {"value": 10, "unit": "шт", "raw": "10ШТ"},
            "document_unit": "ШТ",
            "quantity": 6,
            "quantity_document": 6,
            "price": 35.0,
        }
    )

    result = apply_reference_mapping_to_payload(payload, products=[], packages=[])
    item = result["items"][0]

    assert item["conversion_method"] == "identity_no_rule"
    assert item["quantity_us"] == 6


def test_straws_stay_as_packs_without_a_rule():
    # "150 шт Трубочки ... надо 2 (упак), а не 300".
    payload = _payload(
        {
            "name": "ТРУБОЧКИ Д/КОКТЕЙЛЯ 150ШТ",
            "raw_name": "ТРУБОЧКИ Д/КОКТЕЙЛЯ 150ШТ",
            "package": {"value": 150, "unit": "шт", "raw": "150ШТ"},
            "document_unit": "УП",
            "quantity": 2,
            "quantity_document": 2,
            "price": 60.0,
        }
    )

    result = apply_reference_mapping_to_payload(payload, products=[], packages=[])
    item = result["items"][0]

    assert item["conversion_method"] == "identity_no_rule"
    assert item["quantity_us"] == 2


def test_chips_ambiguity_is_resolved_by_the_rule_not_inferred():
    # "150г Чипсы 15 шт ... если продают пачками - оставить 15, если для
    # приготовления - пересчитать в кг". Same evidence, two legitimate
    # outcomes depending on how the item is actually used -- exactly the
    # judgment call that belongs in a rule, not in code or the AI parser.
    base_item = {
        "name": "ЧИПСЫ КАРТОФЕЛЬНЫЕ 150Г",
        "raw_name": "ЧИПСЫ КАРТОФЕЛЬНЫЕ 150Г",
        "normalized_name_candidate": "Чипсы Картофельные",
        "package": {"value": 150, "unit": "г", "raw": "150Г"},
        "document_unit": "ШТ",
        "quantity": 15,
        "quantity_document": 15,
        "price": 89.0,
    }

    resold_whole = apply_reference_mapping_to_payload(
        _payload(base_item),
        products=[{"Наименование": "Чипсы Картофельные", "Ед. изм.": "шт"}],
        packages=[
            {
                "ID": "chips-resale",
                "Наименование товара УС": "Чипсы Картофельные",
                "Способ пересчета": "Без пересчета",
                "Единица учета в УС": "шт",
                "Активна": "да",
            }
        ],
    )
    assert resold_whole["items"][0]["quantity_us"] == 15

    used_in_cooking = apply_reference_mapping_to_payload(
        _payload(base_item),
        products=[{"Наименование": "Чипсы Картофельные", "Ед. изм.": "кг"}],
        packages=[
            {
                "ID": "chips-cooking",
                "Наименование товара УС": "Чипсы Картофельные",
                "Способ пересчета": "По весу/объему",
                "Единица учета в УС": "кг",
                "Активна": "да",
            }
        ],
    )
    assert used_in_cooking["items"][0]["quantity_us"] == 2.25
