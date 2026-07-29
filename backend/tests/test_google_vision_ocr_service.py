import pytest

from app.services import google_vision_ocr_service as vision_service
from app.services.ocr_service import OcrConfigurationError, OcrProviderError


class _FakeAnnotateCall:
    def __init__(self, response):
        self._response = response

    def execute(self):
        return self._response


class _FakeImagesResource:
    def __init__(self, responses):
        self._queue = list(responses)

    def annotate(self, body):
        return _FakeAnnotateCall(self._queue.pop(0))


class _FakeVisionService:
    def __init__(self, responses):
        self._images = _FakeImagesResource(responses)

    def images(self):
        return self._images


def _text_response(text: str) -> dict:
    return {"responses": [{"fullTextAnnotation": {"text": text}}]}


def _error_response(message: str) -> dict:
    return {"responses": [{"error": {"message": message}}]}


@pytest.fixture(autouse=True)
def _no_real_credentials(monkeypatch, tmp_path):
    monkeypatch.setattr(
        vision_service, "get_google_service_account_credentials", lambda scopes: object()
    )


def test_recognize_invoice_with_google_vision_ocr_single_image(monkeypatch, tmp_path):
    image_path = tmp_path / "invoice.jpg"
    image_path.write_bytes(b"fake-image-bytes")

    fake_service = _FakeVisionService([_text_response("Накладная № 1")])
    monkeypatch.setattr(
        "googleapiclient.discovery.build", lambda *args, **kwargs: fake_service
    )

    result = vision_service.recognize_invoice_with_google_vision_ocr(str(image_path))

    assert result["provider"] == "google_cloud_vision"
    assert result["raw_text"] == "Накладная № 1"
    assert result["pages"] == 1


def test_recognize_invoice_with_google_vision_ocr_multi_page_pdf(monkeypatch, tmp_path):
    pdf_path = tmp_path / "invoice.pdf"
    pdf_path.write_bytes(b"%PDF-1.4 fake")

    monkeypatch.setattr(
        vision_service, "_render_pdf_pages_to_base64_png", lambda path: ["page1==", "page2=="]
    )
    fake_service = _FakeVisionService(
        [_text_response("Страница 1"), _text_response("Страница 2")]
    )
    monkeypatch.setattr(
        "googleapiclient.discovery.build", lambda *args, **kwargs: fake_service
    )

    result = vision_service.recognize_invoice_with_google_vision_ocr(str(pdf_path))

    assert result["pages"] == 2
    assert result["raw_text"] == "Страница 1" + vision_service.PAGE_BREAK_MARKER + "Страница 2"


def test_recognize_invoice_with_google_vision_ocr_raises_on_api_error(monkeypatch, tmp_path):
    image_path = tmp_path / "invoice.png"
    image_path.write_bytes(b"fake-image-bytes")

    fake_service = _FakeVisionService([_error_response("quota exceeded")])
    monkeypatch.setattr(
        "googleapiclient.discovery.build", lambda *args, **kwargs: fake_service
    )

    with pytest.raises(OcrProviderError) as exc_info:
        vision_service.recognize_invoice_with_google_vision_ocr(str(image_path))

    assert exc_info.value.provider == "google_cloud_vision"


def test_recognize_invoice_with_google_vision_ocr_rejects_unsupported_extension(tmp_path):
    bad_path = tmp_path / "invoice.txt"
    bad_path.write_text("not an image")

    with pytest.raises(OcrConfigurationError):
        vision_service.recognize_invoice_with_google_vision_ocr(str(bad_path))


def test_recognize_invoice_with_google_vision_ocr_requires_existing_file(tmp_path):
    missing_path = tmp_path / "missing.jpg"

    with pytest.raises(OcrConfigurationError):
        vision_service.recognize_invoice_with_google_vision_ocr(str(missing_path))
