"""Russian-language text constants for the native Telegram bot.

Ported from the retired n8n workflow's Code nodes (`Normalize Update`,
`Compute Stage`/`Set Stage Reply Text`, reply nodes) — see
docs/wiki/n8n-to-native-bot-migration-plan.md for the node-by-node mapping.
"""

START_TEXT = (
    "Пришлите фото или PDF накладной (можно несколько страниц подряд).\n"
    "Когда все страницы отправлены — нажмите «Готово».\n\n"
    "«Статус» — узнать состояние текущего черновика или последней загрузки.\n"
    "«Сбросить» — очистить текущий черновик и начать заново."
)

UNKNOWN_TEXT_HELP = (
    "Не понял команду. Отправьте фото/PDF страницы накладной, либо используйте кнопки "
    "«Готово», «Статус», «Сбросить»."
)

STARTED_REPLY = "Принял, обрабатываю документ..."

NO_DRAFT_STATUS = "Активного черновика нет."
NO_HISTORY_STATUS = "У этого чата еще нет обработанных документов."
LAST_PROCESSED_PREFIX = "Активного черновика нет. Последний обработанный документ:"

# Stage identifiers as emitted into `pipeline_logs` by
# `document_extraction_service.py` and `bot_gateway_service._process_bot_upload_background`,
# grouped into the four operator-facing progress messages.
_EVIDENCE_STAGES = {
    "collect_evidence_start",
    "ocr_start",
    "ocr_fallback_start",
    "mineru_start",
}
_AI_STAGES = {
    "openai_request_start",
    "reference_mapping_start",
}
_SHEET_STAGES = {
    "google_sheet_start",
}

STAGE_TEXT: dict[str, str] = {
    **{stage: "🔎 Выгружаем данные из документа..." for stage in _EVIDENCE_STAGES},
    **{stage: "🤖 Обрабатываем через ИИ..." for stage in _AI_STAGES},
    **{stage: "📊 Загружаем в таблицу..." for stage in _SHEET_STAGES},
}


def stage_text_for(stage: str) -> str | None:
    return STAGE_TEXT.get(stage)


def format_result_message(status_response) -> str:
    """Build the final Telegram reply once a bot upload finishes (`status_response.completed`)."""
    lines = [status_response.message]
    summary = status_response.document_summary
    if summary:
        if summary.supplier:
            lines.append(f"Поставщик: {summary.supplier}")
        if summary.invoice_number:
            lines.append(f"Номер: {summary.invoice_number}")
        if summary.invoice_date:
            lines.append(f"Дата: {summary.invoice_date}")
        if summary.total_sum is not None:
            lines.append(f"Сумма: {summary.total_sum}")
    if status_response.google_spreadsheet_url:
        lines.append(f"Таблица: {status_response.google_spreadsheet_url}")
    if status_response.google_spreadsheet_error:
        lines.append(f"Ошибка публикации: {status_response.google_spreadsheet_error}")
    return "\n".join(lines)
