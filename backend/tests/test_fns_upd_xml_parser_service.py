from app.services.diadoc_xml_parser_service import parse_diadoc_invoice_xml
from app.services.fns_upd_xml_parser_service import parse_fns_invoice_xml

_SAMPLE_XML = '''<?xml version="1.0" encoding="utf-8"?>
<Файл>
  <Документ>
    <СвСчФакт НомерСчФ="A-15" ДатаСчФ="16.07.2026"/>
    <СвПрод><ИдСв><СвЮЛУч НаимОрг="ООО Поставщик" ИННЮЛ="7701000000"/></ИдСв></СвПрод>
    <ТаблСчФакт СтТовУчНалВсего="1200.00">
      <СведТов НаимТов="Вода 1,5 л" КолТов="2" ЦенаТов="500" СтТовУчНал="1000" НалСт="20%" ОКЕИ_Тов="уп" КодТов="W-1"/>
    </ТаблСчФакт>
  </Документ>
</Файл>'''.encode("utf-8")


def test_parse_fns_invoice_xml_default_provider_matches_diadoc_wrapper():
    via_wrapper = parse_diadoc_invoice_xml(_SAMPLE_XML, file_id="m:e")
    via_shared = parse_fns_invoice_xml(_SAMPLE_XML, file_id="m:e", provider="diadoc")

    assert via_wrapper.document_form == via_shared.document_form
    assert via_wrapper.request_id == via_shared.request_id
    assert via_wrapper.parser_metadata["source_channel"] == "diadoc"


def test_parse_fns_invoice_xml_sbis_provider_uses_sbis_literals():
    payload = parse_fns_invoice_xml(_SAMPLE_XML, file_id="doc-1", provider="sbis")

    assert payload.request_id == "SBIS-doc-1"
    assert payload.document_form == "УПД/ЭДО СБИС"
    assert payload.parser_metadata["source_channel"] == "sbis"
    assert payload.parser_metadata["provider"] == "sbis_xml"
    # Field extraction itself is provider-agnostic — same government schema.
    assert payload.invoice_number == "A-15"
    assert payload.supplier == "ООО Поставщик"
    assert payload.supplier_inn == "7701000000"
    assert payload.total_sum == 1200.0
    assert len(payload.items) == 1
    assert payload.items[0].name == "Вода 1,5 л"
    assert payload.items[0].quantity == 2.0
    assert payload.items[0].price == 500.0
    assert payload.items[0].product_code == "W-1"
