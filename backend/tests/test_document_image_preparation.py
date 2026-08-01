from pathlib import Path

from app.services.document_image_preparation_service import (
    prepare_document_page,
)
from PIL import Image


def test_prepare_document_page_preserves_original_and_creates_derivative(tmp_path: Path, monkeypatch):
    source = tmp_path / "invoice.jpg"
    monkeypatch.setattr(
        "app.services.document_image_preparation_service.settings.uploaded_invoices_dir",
        str(tmp_path / "uploads"),
    )
    Image.new("RGB", (600, 900), "white").save(source)
    original = source.read_bytes()

    result = prepare_document_page(str(source))

    prepared_path = Path(result["prepared_path"])
    assert source.read_bytes() == original
    assert prepared_path.exists()
    assert prepared_path.parent == tmp_path / "uploads" / ".prepared"
    assert result["quality"]["width"] >= 1200
    assert any(value.startswith("upscale_") for value in result["transformations"])
    assert "text_coverage_ratio" in result["quality"]
    assert "review_reasons" in result["quality"]


def test_prepare_document_page_skips_non_image(tmp_path: Path):
    source = tmp_path / "invoice.pdf"
    source.write_bytes(b"%PDF")

    result = prepare_document_page(str(source))

    assert result["prepared_path"] is None
    assert result["quality"]["preparation_skipped"] is True


def test_prepare_document_page_flags_low_text_coverage_for_blank_image(tmp_path: Path, monkeypatch):
    source = tmp_path / "blank.jpg"
    monkeypatch.setattr(
        "app.services.document_image_preparation_service.settings.uploaded_invoices_dir",
        str(tmp_path / "uploads"),
    )
    Image.new("RGB", (1200, 1200), "white").save(source)

    result = prepare_document_page(str(source))

    assert result["quality"]["requires_review"] is True
    assert any("мало текстовых" in value.lower() for value in result["quality"]["review_reasons"])


def _document_like_image(*, touch_left_edge: bool = False) -> Image.Image:
    from PIL import ImageDraw

    image = Image.new("RGB", (1600, 2200), "white")
    draw = ImageDraw.Draw(image)
    start_x = 0 if touch_left_edge else 150
    for y in range(150, 1900, 80):
        for x in range(start_x, start_x + 1150, 55):
            draw.rectangle((x, y, x + 30, y + 25), fill="black")
    return image


def test_prepare_document_page_records_original_resolution(tmp_path: Path, monkeypatch):
    source = tmp_path / "invoice-resolution.jpg"
    monkeypatch.setattr(
        "app.services.document_image_preparation_service.settings.uploaded_invoices_dir",
        str(tmp_path / "uploads"),
    )
    _document_like_image().resize((1000, 1400)).save(source)

    result = prepare_document_page(str(source))
    quality = result["quality"]

    assert quality["original_width"] == 1000
    assert quality["original_height"] == 1400
    assert quality["original_short_side"] == 1000
    assert quality["original_long_side"] == 1400
    assert "low_resolution" in quality["warning_codes"]


def test_skew_estimation_detects_noticeable_document_tilt():
    from app.services.document_image_preparation_service import (
        _estimate_skew_angle,
    )

    rotated = _document_like_image().rotate(8, expand=False, fillcolor="white")

    angle = _estimate_skew_angle(rotated)

    assert angle is not None
    assert 7.0 <= abs(angle) <= 9.0


def test_edge_touch_detection_flags_probable_crop():
    from app.services.document_image_preparation_service import (
        _edge_touch_metrics,
    )

    normal = _edge_touch_metrics(_document_like_image())
    cropped = _edge_touch_metrics(_document_like_image(touch_left_edge=True))

    assert normal["possible_cropped_document"] is False
    assert cropped["possible_cropped_document"] is True
    assert cropped["edge_touch_count"] >= 2
    assert cropped["edge_touch_ratio"] > normal["edge_touch_ratio"]


def test_two_quality_warnings_recommend_replacement():
    from app.services.document_image_preparation_service import (
        _quality_assessment,
    )

    assessment = _quality_assessment(
        {
            "quality_metrics_available": True,
            "original_short_side": 1200,
            "original_blur_score": 100.0,
            "original_glare_ratio": 0.1,
            "original_dark_ratio": 0.1,
            "original_clipping_ratio": 0.1,
            "detected_skew_angle": 8.0,
            "skew_correction_applied": True,
            "edge_touch_ratio": 0.0,
            "edge_touch_count": 0,
            "text_coverage_ratio": 0.1,
        }
    )

    assert assessment["critical_error_count"] == 0
    assert assessment["warning_count"] == 2
    assert set(assessment["warning_codes"]) == {"low_resolution", "excessive_skew"}
    assert assessment["stop_recommended"] is True
    assert assessment["quality_decision"] == "reject"


def test_single_warning_does_not_reject_document():
    from app.services.document_image_preparation_service import (
        _quality_assessment,
    )

    assessment = _quality_assessment(
        {
            "quality_metrics_available": True,
            "original_short_side": 1200,
            "original_blur_score": 100.0,
            "original_glare_ratio": 0.1,
            "original_dark_ratio": 0.1,
            "original_clipping_ratio": 0.1,
            "detected_skew_angle": 0.0,
            "edge_touch_ratio": 0.0,
            "edge_touch_count": 0,
            "text_coverage_ratio": 0.1,
        }
    )

    assert assessment["warning_count"] == 1
    assert assessment["stop_recommended"] is False
    assert assessment["quality_decision"] == "review"


def test_critical_resolution_rejects_without_second_warning():
    from app.services.document_image_preparation_service import (
        _quality_assessment,
    )

    assessment = _quality_assessment(
        {
            "quality_metrics_available": True,
            "original_short_side": 600,
            "original_blur_score": 100.0,
            "original_glare_ratio": 0.1,
            "original_dark_ratio": 0.1,
            "original_clipping_ratio": 0.1,
            "detected_skew_angle": 0.0,
            "edge_touch_ratio": 0.0,
            "edge_touch_count": 0,
            "text_coverage_ratio": 0.1,
        }
    )

    assert assessment["warning_count"] == 0
    assert assessment["critical_error_codes"] == ["critical_low_resolution"]
    assert assessment["stop_recommended"] is True


def test_resolution_below_900_is_only_a_warning():
    from app.services.document_image_preparation_service import (
        _quality_assessment,
    )

    assessment = _quality_assessment(
        {
            "quality_metrics_available": True,
            "original_short_side": 820,
            "original_blur_score": 100.0,
            "original_glare_ratio": 0.1,
            "original_dark_ratio": 0.1,
            "original_clipping_ratio": 0.1,
            "detected_skew_angle": 0.0,
            "edge_touch_ratio": 0.0,
            "edge_touch_count": 0,
            "text_coverage_ratio": 0.1,
        }
    )

    assert assessment["warning_codes"] == ["low_resolution"]
    assert assessment["critical_error_codes"] == []
    assert assessment["quality_decision"] == "review"
    assert assessment["stop_recommended"] is False


def test_resolution_below_900_rejects_with_blur_warning():
    from app.services.document_image_preparation_service import (
        _quality_assessment,
    )

    assessment = _quality_assessment(
        {
            "quality_metrics_available": True,
            "original_short_side": 820,
            "original_blur_score": 20.0,
            "original_glare_ratio": 0.1,
            "original_dark_ratio": 0.1,
            "original_clipping_ratio": 0.1,
            "detected_skew_angle": 0.0,
            "edge_touch_ratio": 0.0,
            "edge_touch_count": 0,
            "text_coverage_ratio": 0.1,
        }
    )

    assert set(assessment["warning_codes"]) == {"low_resolution", "blur"}
    assert assessment["critical_error_codes"] == []
    assert assessment["quality_decision"] == "reject"
    assert assessment["stop_recommended"] is True


def test_white_document_background_is_not_treated_as_critical_glare(tmp_path: Path, monkeypatch):
    source = tmp_path / "clean-document.jpg"
    monkeypatch.setattr(
        "app.services.document_image_preparation_service.settings.uploaded_invoices_dir",
        str(tmp_path / "uploads"),
    )
    _document_like_image().save(source, quality=95)

    quality = prepare_document_page(str(source))["quality"]

    assert "critical_lighting" not in quality["critical_error_codes"]
    assert quality["stop_recommended"] is False
    assert quality["quality_decision"] == "accept"


def test_quarter_turn_does_not_rotate_dense_portrait_document():
    from app.services.document_image_preparation_service import (
        _quarter_turn_rotation,
    )

    assert _quarter_turn_rotation(_document_like_image()) is None


def _oriented_document_image() -> Image.Image:
    from PIL import ImageDraw

    image = Image.new("RGB", (1600, 2200), "white")
    draw = ImageDraw.Draw(image)
    for y in range(120, 620, 55):
        for x in range(120, 1450, 48):
            draw.rectangle((x, y, x + 28, y + 22), fill="black")
    for y in range(760, 1540, 105):
        for x in range(180, 1250, 70):
            draw.rectangle((x, y, x + 34, y + 24), fill="black")
    draw.rectangle((180, 1750, 620, 1780), fill="black")
    return image


def test_quarter_turn_selects_counterclockwise_for_clockwise_document(monkeypatch):
    from PIL import ImageChops

    from app.services import (
        document_image_preparation_service as service,
    )

    upright = _oriented_document_image()
    sideways_clockwise = upright.rotate(-90, expand=True)
    monkeypatch.setattr(
        service,
        "_tesseract_orientation",
        lambda image: {
            "rotate_clockwise": 270,
            "confidence": 14.0,
            "script": "Latin",
            "error": None,
        },
    )

    rotation = service._quarter_turn_rotation(sideways_clockwise)
    corrected = sideways_clockwise.rotate(rotation or 0, expand=True)

    assert rotation == 90
    assert ImageChops.difference(corrected, upright).getbbox() is None


def test_quarter_turn_selects_clockwise_for_counterclockwise_document(monkeypatch):
    from PIL import ImageChops

    from app.services import (
        document_image_preparation_service as service,
    )

    upright = _oriented_document_image()
    sideways_counterclockwise = upright.rotate(90, expand=True)
    monkeypatch.setattr(
        service,
        "_tesseract_orientation",
        lambda image: {
            "rotate_clockwise": 90,
            "confidence": 14.0,
            "script": "Latin",
            "error": None,
        },
    )

    rotation = service._quarter_turn_rotation(sideways_counterclockwise)
    corrected = sideways_counterclockwise.rotate(rotation or 0, expand=True)

    assert rotation == -90
    assert ImageChops.difference(corrected, upright).getbbox() is None


def _bottom_heavy_document_image() -> Image.Image:
    from PIL import ImageDraw

    image = Image.new("RGB", (1600, 2200), "white")
    draw = ImageDraw.Draw(image)
    draw.rectangle((180, 180, 760, 215), fill="black")
    for y in range(1250, 2050, 60):
        for x in range(120, 1480, 48):
            draw.rectangle((x, y, x + 28, y + 22), fill="black")
    return image


def _symmetric_document_image() -> Image.Image:
    from PIL import ImageDraw

    image = Image.new("RGB", (1600, 2200), "white")
    draw = ImageDraw.Draw(image)
    for y in list(range(180, 850, 70)) + list(range(1350, 2020, 70)):
        for x in range(140, 1460, 52):
            draw.rectangle((x, y, x + 30, y + 23), fill="black")
    return image


def test_quarter_turn_direction_does_not_depend_on_top_heavy_layout(monkeypatch):
    from PIL import ImageChops

    from app.services import (
        document_image_preparation_service as service,
    )

    upright = _bottom_heavy_document_image()
    sideways = upright.rotate(-90, expand=True)
    monkeypatch.setattr(
        service,
        "_tesseract_orientation",
        lambda image: {
            "rotate_clockwise": 270,
            "confidence": 12.5,
            "script": "Latin",
            "error": None,
        },
    )

    rotation = service._quarter_turn_rotation(sideways)
    corrected = sideways.rotate(rotation or 0, expand=True)

    assert rotation == 90
    assert ImageChops.difference(corrected, upright).getbbox() is None


def test_ambiguous_sideways_document_is_rejected(monkeypatch):
    from app.services import (
        document_image_preparation_service as service,
    )

    sideways = _symmetric_document_image().rotate(-90, expand=True)
    monkeypatch.setattr(
        service,
        "_tesseract_orientation",
        lambda image: {
            "rotate_clockwise": 270,
            "confidence": 2.0,
            "script": "Latin",
            "error": None,
        },
    )

    orientation = service._orientation_analysis(sideways)
    assessment = service._quality_assessment(
        {
            "quality_metrics_available": True,
            "original_short_side": 1600,
            "original_blur_score": 100.0,
            "original_glare_ratio": 0.1,
            "original_dark_ratio": 0.1,
            "original_clipping_ratio": 0.1,
            "orientation_unresolved": orientation["unresolved"],
            "orientation_confidence": orientation["confidence"],
            "detected_skew_angle": 0.0,
            "edge_touch_ratio": 0.0,
            "edge_touch_count": 0,
            "text_coverage_ratio": 0.1,
        }
    )

    assert orientation["rotation_angle"] is None
    assert orientation["quarter_turn_detected"] is True
    assert orientation["unresolved"] is True
    assert assessment["critical_error_codes"] == [
        "critical_orientation_unresolved"
    ]
    assert assessment["stop_recommended"] is True
    assert assessment["quality_decision"] == "reject"


def test_prepare_document_page_rejects_unresolved_sideways_orientation(
    tmp_path: Path,
    monkeypatch,
):
    from app.services import (
        document_image_preparation_service as service,
    )

    source = tmp_path / "ambiguous-sideways.jpg"
    _symmetric_document_image().rotate(-90, expand=True).save(source, quality=95)
    monkeypatch.setattr(
        service.settings,
        "uploaded_invoices_dir",
        str(tmp_path / "uploads"),
    )
    monkeypatch.setattr(
        service,
        "_tesseract_orientation",
        lambda image: {
            "rotate_clockwise": 270,
            "confidence": 2.0,
            "script": "Latin",
            "error": None,
        },
    )

    result = service.prepare_document_page(str(source))
    quality = result["quality"]

    assert quality["quarter_turn_detected"] is True
    assert quality["quarter_turn_applied"] is False
    assert quality["orientation_unresolved"] is True
    assert "critical_orientation_unresolved" in quality["critical_error_codes"]
    assert quality["stop_recommended"] is True
    assert quality["quality_decision"] == "reject"


def test_orientation_detection_error_rejects_sideways_document(monkeypatch):
    from app.services import (
        document_image_preparation_service as service,
    )

    sideways = _oriented_document_image().rotate(90, expand=True)
    monkeypatch.setattr(
        service,
        "_tesseract_orientation",
        lambda image: {
            "rotate_clockwise": None,
            "confidence": None,
            "script": None,
            "error": "Tesseract is unavailable",
        },
    )

    orientation = service._orientation_analysis(sideways)

    assert orientation["rotation_angle"] is None
    assert orientation["unresolved"] is True
    assert orientation["error"] == "Tesseract is unavailable"


def test_verified_deskew_rejects_candidate_that_increases_skew(monkeypatch):
    from app.services import (
        document_image_preparation_service as service,
    )

    source = _document_like_image().rotate(8, expand=False, fillcolor="white")
    worse_candidate = source.rotate(8, expand=False, fillcolor="white")
    monkeypatch.setattr(
        service,
        "_deskew_image",
        lambda image, angle: (worse_candidate, angle),
    )
    monkeypatch.setattr(service, "_estimate_skew_angle", lambda image: 16.0)

    result, applied, residual, attempted = service._verified_deskew_image(source, 8.0)

    assert result is source
    assert attempted == 8.0
    assert applied is None
    assert residual == 8.0


def test_quality_assessment_uses_residual_skew_after_correction():
    from app.services.document_image_preparation_service import (
        _quality_assessment,
    )

    assessment = _quality_assessment(
        {
            "quality_metrics_available": True,
            "original_short_side": 1600,
            "original_blur_score": 100.0,
            "original_glare_ratio": 0.1,
            "original_dark_ratio": 0.1,
            "original_clipping_ratio": 0.1,
            "detected_skew_angle": 8.0,
            "deskew_angle_applied": 8.0,
            "residual_skew_angle": 0.2,
            "skew_correction_applied": True,
            "edge_touch_ratio": 0.0,
            "edge_touch_count": 0,
            "text_coverage_ratio": 0.1,
        }
    )

    assert "excessive_skew" not in assessment["warning_codes"]
    assert "critical_skew" not in assessment["critical_error_codes"]
    assert assessment["quality_decision"] == "accept"


def test_confident_upside_down_orientation_is_corrected(monkeypatch):
    from PIL import ImageChops

    from app.services import (
        document_image_preparation_service as service,
    )

    upright = _oriented_document_image()
    upside_down = upright.rotate(180, expand=True)
    monkeypatch.setattr(
        service,
        "_tesseract_orientation",
        lambda image: {
            "rotate_clockwise": 180,
            "confidence": 12.0,
            "script": "Latin",
            "error": None,
        },
    )

    orientation = service._orientation_analysis(upside_down)
    corrected = upside_down.rotate(orientation["rotation_angle"] or 0, expand=True)

    assert orientation["rotation_angle"] == 180
    assert orientation["detected_rotation"] == 180
    assert orientation["unresolved"] is False
    assert ImageChops.difference(corrected, upright).getbbox() is None


def test_low_confidence_upside_down_hint_is_not_a_standalone_rejection(
    monkeypatch,
):
    from app.services import (
        document_image_preparation_service as service,
    )

    upside_down = _oriented_document_image().rotate(180, expand=True)
    monkeypatch.setattr(
        service,
        "_tesseract_orientation",
        lambda image: {
            "rotate_clockwise": 180,
            "confidence": 1.77,
            "script": "Latin",
            "error": None,
        },
    )

    orientation = service._orientation_analysis(upside_down)
    assessment = service._quality_assessment(
        {
            "quality_metrics_available": True,
            "original_short_side": 1600,
            "original_blur_score": 100.0,
            "original_glare_ratio": 0.1,
            "original_dark_ratio": 0.1,
            "original_clipping_ratio": 0.1,
            "orientation_rotation_detected": orientation["detected_rotation"],
            "orientation_unresolved": orientation["unresolved"],
            "orientation_confidence": orientation["confidence"],
            "detected_skew_angle": 0.0,
            "edge_touch_ratio": 0.0,
            "edge_touch_count": 0,
            "text_coverage_ratio": 0.1,
        }
    )

    assert orientation["rotation_angle"] is None
    assert orientation["detected_rotation"] == 180
    assert orientation["unconfirmed_nonzero_hint"] is False
    assert orientation["unconfirmed_upside_down_hint"] is True
    assert orientation["upside_down_confirmation_attempted"] is True
    assert orientation["upside_down_confirmed"] is False
    assert orientation["unresolved_reason"] is None
    assert orientation["unresolved"] is False
    assert assessment["critical_error_codes"] == []
    assert assessment["quality_decision"] == "accept"
    assert assessment["stop_recommended"] is False


def test_low_confidence_upside_down_hint_is_applied_when_recheck_confirms(
    monkeypatch,
):
    from app.services import (
        document_image_preparation_service as service,
    )

    responses = iter(
        [
            {
                "rotate_clockwise": 180,
                "confidence": 1.5,
                "script": "Latin",
                "error": None,
            },
            {
                "rotate_clockwise": 0,
                "confidence": 4.0,
                "script": "Latin",
                "error": None,
            },
        ]
    )
    monkeypatch.setattr(service, "_tesseract_orientation", lambda _image: next(responses))

    orientation = service._orientation_analysis(
        _oriented_document_image().rotate(180, expand=True)
    )

    assert orientation["rotation_angle"] == 180
    assert orientation["upside_down_confirmation_attempted"] is True
    assert orientation["upside_down_confirmed"] is True
    assert orientation["unconfirmed_upside_down_hint"] is False
    assert orientation["unresolved"] is False


def test_low_confidence_zero_degree_does_not_reject_upright_document(monkeypatch):
    from app.services import (
        document_image_preparation_service as service,
    )

    monkeypatch.setattr(
        service,
        "_tesseract_orientation",
        lambda image: {
            "rotate_clockwise": 0,
            "confidence": 1.0,
            "script": "Latin",
            "error": None,
        },
    )

    orientation = service._orientation_analysis(_oriented_document_image())

    assert orientation["rotation_angle"] is None
    assert orientation["detected_rotation"] == 0
    assert orientation["unconfirmed_nonzero_hint"] is False
    assert orientation["unresolved"] is False


def test_prepare_document_page_does_not_reject_low_confidence_180_hint(
    tmp_path: Path,
    monkeypatch,
):
    from app.services import (
        document_image_preparation_service as service,
    )

    source = tmp_path / "upside-down.jpg"
    _oriented_document_image().rotate(180, expand=True).save(source, quality=95)
    monkeypatch.setattr(
        service.settings,
        "uploaded_invoices_dir",
        str(tmp_path / "uploads"),
    )
    monkeypatch.setattr(
        service,
        "_tesseract_orientation",
        lambda image: {
            "rotate_clockwise": 180,
            "confidence": 1.77,
            "script": "Latin",
            "error": None,
        },
    )

    quality = service.prepare_document_page(str(source))["quality"]

    assert quality["orientation_rotation_detected"] == 180
    assert quality["orientation_correction_applied"] is False
    assert quality["orientation_unresolved"] is False
    assert quality["orientation_unconfirmed_upside_down_hint"] is True
    assert quality["orientation_upside_down_confirmation_attempted"] is True
    assert "critical_orientation_unresolved" not in quality["critical_error_codes"]
    assert quality["stop_recommended"] is False


def _mock_quality_metrics(
    *,
    blur_score: float,
    width: int = 1600,
    height: int = 2200,
) -> dict[str, object]:
    return {
        "width": width,
        "height": height,
        "blur_score": blur_score,
        "glare_ratio": 0.05,
        "dark_ratio": 0.02,
        "clipping_ratio": 0.05,
        "text_coverage_ratio": 0.12,
        "brightness_mean": 220.0,
        "brightness_std": 45.0,
        "possible_quarter_turn": False,
        "quality_metrics_available": True,
    }


def _mock_edge_metrics() -> dict[str, object]:
    return {
        "edge_touch_ratio": 0.0,
        "edge_touch_count": 0,
        "text_block_count": 20,
        "edge_margin_pixels": 20,
        "possible_cropped_document": False,
        "edge_touch_metrics_available": True,
    }


def test_automatic_improvement_can_recover_initially_bad_quality(
    tmp_path: Path,
    monkeypatch,
):
    from app.services import (
        document_image_preparation_service as service,
    )

    source = tmp_path / "recoverable-blur.jpg"
    _document_like_image().save(source, quality=95)
    metrics = iter(
        [
            _mock_quality_metrics(blur_score=5.0),
            _mock_quality_metrics(blur_score=100.0),
        ]
    )
    monkeypatch.setattr(service.settings, "uploaded_invoices_dir", str(tmp_path / "uploads"))
    monkeypatch.setattr(service, "_quality_metrics", lambda _image: next(metrics))
    monkeypatch.setattr(service, "_edge_touch_metrics", lambda _image: _mock_edge_metrics())
    monkeypatch.setattr(
        service,
        "_orientation_analysis",
        lambda _image: service._empty_orientation_analysis(),
    )
    monkeypatch.setattr(service, "_estimate_skew_angle", lambda _image: 0.0)
    monkeypatch.setattr(service, "_perspective_crop", lambda _image: None)

    quality = service.prepare_document_page(str(source))["quality"]

    assert quality["original_quality"]["quality_decision"] == "reject"
    assert quality["prepared_quality"]["quality_decision"] == "accept"
    assert quality["quality_decision"] == "accept"
    assert quality["stop_recommended"] is False
    assert quality["improvement_successful"] is True
    assert quality["final_quality_gate_stage"] == "after_automatic_improvement"
    assert quality["original_blur_score"] == 5.0
    assert quality["blur_score"] == 100.0


def test_image_is_rejected_only_when_prepared_quality_remains_bad(
    tmp_path: Path,
    monkeypatch,
):
    from app.services import (
        document_image_preparation_service as service,
    )

    source = tmp_path / "unrecoverable-blur.jpg"
    _document_like_image().save(source, quality=95)
    metrics = iter(
        [
            _mock_quality_metrics(blur_score=5.0),
            _mock_quality_metrics(blur_score=6.0),
            _mock_quality_metrics(blur_score=5.0),
        ]
    )
    monkeypatch.setattr(service.settings, "uploaded_invoices_dir", str(tmp_path / "uploads"))
    monkeypatch.setattr(service, "_quality_metrics", lambda _image: next(metrics))
    monkeypatch.setattr(service, "_edge_touch_metrics", lambda _image: _mock_edge_metrics())
    monkeypatch.setattr(
        service,
        "_orientation_analysis",
        lambda _image: service._empty_orientation_analysis(),
    )
    monkeypatch.setattr(service, "_estimate_skew_angle", lambda _image: 0.0)
    monkeypatch.setattr(service, "_perspective_crop", lambda _image: None)

    quality = service.prepare_document_page(str(source))["quality"]

    assert quality["original_quality"]["quality_decision"] == "reject"
    assert quality["prepared_quality"]["quality_decision"] == "reject"
    assert quality["quality_decision"] == "reject"
    assert quality["stop_recommended"] is True
    assert quality["improvement_successful"] is False
    assert "critical_blur" in quality["critical_error_codes"]


def test_automatic_improvement_rolls_back_when_quality_becomes_worse(
    tmp_path: Path,
    monkeypatch,
):
    from app.services import (
        document_image_preparation_service as service,
    )

    source = tmp_path / "quality-regression.jpg"
    original_image = _document_like_image()
    original_image.save(source, quality=95)
    metrics = iter(
        [
            _mock_quality_metrics(blur_score=100.0),
            _mock_quality_metrics(
                blur_score=100.0,
                width=1490,
                height=2048,
            ),
            _mock_quality_metrics(blur_score=100.0),
        ]
    )
    normal_edge = _mock_edge_metrics()
    cropped_edge = {
        **_mock_edge_metrics(),
        "edge_touch_ratio": 0.35,
        "edge_touch_count": 7,
        "possible_cropped_document": True,
    }
    edge_metrics = iter([normal_edge, cropped_edge, normal_edge])
    monkeypatch.setattr(
        service.settings,
        "uploaded_invoices_dir",
        str(tmp_path / "uploads"),
    )
    monkeypatch.setattr(service, "_quality_metrics", lambda _image: next(metrics))
    monkeypatch.setattr(
        service,
        "_edge_touch_metrics",
        lambda _image: next(edge_metrics),
    )
    monkeypatch.setattr(
        service,
        "_orientation_analysis",
        lambda _image: service._empty_orientation_analysis(),
    )
    monkeypatch.setattr(service, "_estimate_skew_angle", lambda _image: 0.0)
    monkeypatch.setattr(
        service,
        "_perspective_crop",
        lambda image: image.resize((1490, 2048)),
    )

    result = service.prepare_document_page(str(source))
    quality = result["quality"]

    assert quality["original_quality"]["quality_decision"] == "accept"
    assert quality["attempted_prepared_quality"]["quality_decision"] == "reject"
    assert quality["prepared_quality"]["quality_decision"] == "accept"
    assert quality["quality_decision"] == "accept"
    assert quality["automatic_improvement_rolled_back"] is True
    assert quality["selected_image_variant"] == "original_after_exif"
    assert "document_perspective_crop" in quality["attempted_transformations"]
    assert result["transformations"] == ["automatic_improvement_rolled_back"]
    with Image.open(result["prepared_path"]) as prepared:
        assert prepared.size == original_image.size


def test_orientation_ambiguity_must_be_resolved_after_improvement():
    from app.services import (
        document_image_preparation_service as service,
    )

    initial = {
        **service._empty_orientation_analysis(),
        "detected_rotation": 180,
        "confidence": 1.5,
        "unconfirmed_nonzero_hint": True,
        "unresolved_reason": "nonzero_osd_below_confidence",
        "unresolved": True,
    }
    enhanced = {
        **service._empty_orientation_analysis(),
        "detected_rotation": 0,
        "confidence": 1.0,
    }

    final = service._final_orientation_after_improvement(
        initial,
        None,
        enhanced,
        None,
    )

    assert final["unresolved"] is True
    assert final["detected_rotation"] == 180
    assert final["unresolved_reason"] == "orientation_ambiguous_after_improvement"


def test_confident_upright_result_resolves_initial_orientation_ambiguity():
    from app.services import (
        document_image_preparation_service as service,
    )

    initial = {
        **service._empty_orientation_analysis(),
        "detected_rotation": 180,
        "confidence": 1.5,
        "unconfirmed_nonzero_hint": True,
        "unresolved_reason": "nonzero_osd_below_confidence",
        "unresolved": True,
    }
    enhanced = {
        **service._empty_orientation_analysis(),
        "detected_rotation": 0,
        "confidence": 12.0,
    }

    final = service._final_orientation_after_improvement(
        initial,
        None,
        enhanced,
        None,
    )

    assert final["unresolved"] is False
    assert final["detected_rotation"] == 0


def test_sparse_black_text_on_white_background_is_not_bad_lighting():
    from PIL import ImageDraw

    from app.services import (
        document_image_preparation_service as service,
    )

    image = Image.new("RGB", (1600, 2200), "white")
    draw = ImageDraw.Draw(image)
    for y in range(180, 1900, 90):
        draw.text((160, y), "INVOICE 12345 ITEM 10 250.00", fill="black")

    quality = service._quality_metrics(image)
    assessment = service._quality_assessment(quality)

    assert quality["foreground_contrast"] >= service.LOW_FOREGROUND_CONTRAST
    assert "bad_lighting" not in assessment["warning_codes"]
    assert "critical_lighting" not in assessment["critical_error_codes"]


def test_upscale_does_not_clear_critical_original_resolution():
    from app.services.document_image_preparation_service import (
        _quality_assessment,
    )

    assessment = _quality_assessment(
        {
            "quality_metrics_available": True,
            "width": 1200,
            "height": 1800,
            "original_short_side": 600,
            "blur_score": 100.0,
            "glare_ratio": 0.1,
            "dark_ratio": 0.1,
            "clipping_ratio": 0.1,
            "detected_skew_angle": 0.0,
            "edge_touch_ratio": 0.0,
            "edge_touch_count": 0,
            "text_coverage_ratio": 0.1,
        }
    )

    assert assessment["critical_error_codes"] == ["critical_low_resolution"]
    assert assessment["quality_decision"] == "reject"
    assert assessment["stop_recommended"] is True


def test_prepare_document_page_keeps_critical_original_resolution_after_upscale(
    tmp_path: Path,
    monkeypatch,
):
    from app.services import (
        document_image_preparation_service as service,
    )

    source = tmp_path / "critically-small-document.jpg"
    _document_like_image().resize((600, 900)).save(source, quality=95)
    monkeypatch.setattr(
        service.settings,
        "uploaded_invoices_dir",
        str(tmp_path / "uploads"),
    )

    result = service.prepare_document_page(str(source))
    quality = result["quality"]

    assert quality["original_short_side"] == 600
    assert quality["width"] > quality["original_width"]
    assert any(
        transformation.startswith("upscale_")
        for transformation in quality["attempted_transformations"]
    )
    assert "critical_low_resolution" in quality["critical_error_codes"]
    assert quality["quality_decision"] == "reject"
    assert quality["stop_recommended"] is True
