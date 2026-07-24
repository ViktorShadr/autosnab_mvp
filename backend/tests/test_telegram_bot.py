import asyncio
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ["DATABASE_URL"] = "sqlite:///:memory:"

from app.config import settings  # noqa: E402
from app.schemas.invoice_review import BotDocumentSummary, BotUploadStatusResponse, PipelineLogEntry  # noqa: E402
from app.telegram_bot import poller  # noqa: E402
from app.telegram_bot.handlers import _matches  # noqa: E402
from app.telegram_bot.keyboard import DRAFT_ACTIONS_KEYBOARD, sheet_link_keyboard  # noqa: E402
from app.telegram_bot.messages import format_result_message, stage_text_for  # noqa: E402


def test_matches_is_case_and_whitespace_insensitive():
    predicate = _matches("готово", "/done", "done")
    assert predicate("Готово")
    assert predicate("  ГОТОВО  ")
    assert predicate("/done")
    assert not predicate("статус")


def test_matches_handles_none_and_empty_text():
    predicate = _matches("готово")
    assert not predicate(None)
    assert not predicate("")


def test_draft_actions_keyboard_has_done_and_reset_callbacks():
    buttons = [button for row in DRAFT_ACTIONS_KEYBOARD.inline_keyboard for button in row]
    assert [b.callback_data for b in buttons] == ["bot:done", "bot:reset"]


def test_sheet_link_keyboard_opens_the_given_url():
    keyboard = sheet_link_keyboard("https://sheets.example/doc")
    button = keyboard.inline_keyboard[0][0]
    assert button.url == "https://sheets.example/doc"


def test_stage_text_for_groups_known_stages_and_ignores_unknown():
    assert stage_text_for("ocr_start") == stage_text_for("collect_evidence_start")
    assert stage_text_for("openai_request_start") == stage_text_for("reference_mapping_start")
    assert stage_text_for("google_sheet_start") is not None
    assert stage_text_for("job_queued") is None
    assert stage_text_for("totally_unknown_stage") is None


def test_format_result_message_includes_summary_but_not_the_raw_sheet_link():
    """The sheet URL is surfaced as an inline button (`sheet_link_keyboard`), not repeated
    as raw text in the message body."""
    status = BotUploadStatusResponse(
        upload_id="bot-upload-1",
        status="transferred_to_review",
        message="Документ обработан и передан в модуль проверки данных.",
        completed=True,
        source_channel="telegram_bot",
        document_kind="primary_document",
        files_count=1,
        original_filename="page-1.jpg",
        google_spreadsheet_url="https://sheets.example/doc",
        document_summary=BotDocumentSummary(
            supplier="ООО Тест",
            invoice_number="INV-1",
            invoice_date="2026-07-21",
            total_sum=123.45,
        ),
    )

    text = format_result_message(status)

    assert "Документ обработан и передан в модуль проверки данных." in text
    assert "Поставщик: ООО Тест" in text
    assert "Номер: INV-1" in text
    assert "Сумма: 123.45" in text
    assert "https://sheets.example/doc" not in text


def test_format_result_message_without_summary_is_just_the_message():
    status = BotUploadStatusResponse(
        upload_id="bot-upload-2",
        status="unsupported_format",
        message="Формат файла пока не поддерживается.",
        completed=True,
        source_channel="telegram_bot",
        document_kind="primary_document",
        files_count=1,
        original_filename="invoice.xml",
    )

    assert format_result_message(status) == "Формат файла пока не поддерживается."


class _FakeBot:
    def __init__(self):
        self.sent: list[str] = []
        self.edited: list[str] = []
        self.sent_reply_markups: list = []

    async def send_message(self, chat_id, text, reply_markup=None):
        self.sent.append(text)
        self.sent_reply_markups.append(reply_markup)

    async def edit_message_text(self, text, chat_id, message_id):
        self.edited.append(text)


def _status(stages: list[str], *, completed: bool = False, message: str = "Готово") -> BotUploadStatusResponse:
    return BotUploadStatusResponse(
        upload_id="bot-upload-poll",
        status="processing",
        message=message,
        completed=completed,
        source_channel="telegram_bot",
        document_kind="primary_document",
        files_count=1,
        original_filename="page-1.jpg",
        pipeline_logs=[PipelineLogEntry(stage=stage, status="running", message=stage) for stage in stages],
    )


def test_poll_loop_edits_progress_message_once_per_stage_even_as_pipeline_logs_keeps_growing(monkeypatch):
    """Regression test for a real production bug (img_14.png, 2026-07-21): the poll loop used to
    re-scan the whole (ever-growing) `pipeline_logs` list on every tick and compare against a single
    last-sent value, so any tick with 2+ distinct stage groups re-sent every earlier stage message
    again — producing dozens of alternating "Выгружаем данные"/"Обрабатываем через ИИ" messages.
    """
    monkeypatch.setattr(settings, "telegram_bot_poll_interval_seconds", 0)
    monkeypatch.setattr(settings, "telegram_bot_max_poll_attempts", 10)

    ticks = [
        _status(["collect_evidence_start"]),
        _status(["collect_evidence_start", "openai_request_start"]),
        _status(["collect_evidence_start", "openai_request_start", "google_sheet_start"]),
        _status(
            ["collect_evidence_start", "openai_request_start", "google_sheet_start"],
            completed=True,
            message="Документ обработан.",
        ),
    ]
    call_count = {"n": 0}

    def fake_fetch_status(upload_id):
        index = min(call_count["n"], len(ticks) - 1)
        call_count["n"] += 1
        return ticks[index]

    monkeypatch.setattr(poller, "_fetch_status", fake_fetch_status)

    bot = _FakeBot()
    asyncio.run(poller._poll_loop(bot, "chat-1", "upload-1", progress_message_id=42))

    assert bot.edited == [
        "🔎 Выгружаем данные из документа...",
        "🤖 Обрабатываем через ИИ...",
        "📊 Загружаем в таблицу...",
    ]
    assert bot.sent == ["Документ обработан."]
