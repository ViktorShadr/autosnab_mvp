from __future__ import annotations

from pathlib import Path
from typing import Any
from uuid import uuid4

from app.config import settings

SUPPORTED_IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".tif", ".tiff", ".bmp"}
DESKEW_MIN_ANGLE = 1.2
DESKEW_MAX_ANGLE = 12.0
SKEW_WARNING_ANGLE = 7.0
SKEW_CRITICAL_ANGLE = 15.0
MIN_QUALITY_SHORT_SIDE = 1500
LOW_RESOLUTION_SHORT_SIDE = 900
CRITICAL_QUALITY_SHORT_SIDE = 650
LOW_TEXT_COVERAGE = 0.015
CRITICAL_TEXT_COVERAGE = 0.003
HIGH_GLARE_RATIO = 0.28
CRITICAL_GLARE_RATIO = 0.95
HIGH_DARK_RATIO = 0.45
CRITICAL_DARK_RATIO = 0.72
LOW_BLUR_SCORE = 25.0
CRITICAL_BLUR_SCORE = 8.0
HIGH_CLIPPING_RATIO = 0.22
CRITICAL_CLIPPING_RATIO = 0.95
EDGE_MARGIN_RATIO = 0.015
HIGH_EDGE_TOUCH_RATIO = 0.20
CRITICAL_EDGE_TOUCH_RATIO = 0.60
MIN_EDGE_TOUCH_BLOCKS = 2
LOW_BRIGHTNESS_MEAN = 70.0
CRITICAL_BRIGHTNESS_MEAN = 35.0
HIGH_BRIGHTNESS_MEAN = 238.0
CRITICAL_HIGH_BRIGHTNESS_MEAN = 247.0
LOW_BRIGHTNESS_STD = 18.0
CRITICAL_BRIGHTNESS_STD = 10.0
LOW_FOREGROUND_CONTRAST = 35.0
CRITICAL_FOREGROUND_CONTRAST = 15.0
QUARTER_TURN_MIN_ASPECT_RATIO = 1.10
QUARTER_TURN_MIN_PROJECTION_RATIO = 1.25
QUARTER_TURN_MIN_LINE_RATIO = 2.0
QUARTER_TURN_MIN_AXIS_ANGLE = 70.0
QUARTER_TURN_MAX_AXIS_ANGLE = 20.0
ORIENTATION_OSD_MIN_CONFIDENCE = 6.0
ORIENTATION_180_CONFIRMATION_MIN_CONFIDENCE = 3.0
ORIENTATION_180_CONFIRMATION_GAIN = 0.75
ORIENTATION_OSD_MAX_DIMENSION = 2200
ORIENTATION_OSD_MIN_DIMENSION = 1200
DESKEW_IMPROVEMENT_EPSILON = 0.25


def prepare_document_page(file_path: str) -> dict[str, Any]:
    path = Path(file_path)
    if path.suffix.lower() not in SUPPORTED_IMAGE_EXTENSIONS:
        return {
            "prepared_path": None,
            "transformations": [],
            "quality": {"preparation_skipped": True},
        }

    from PIL import Image, ImageOps

    transformations: list[str] = []
    with Image.open(path) as source_image:
        original_size = source_image.size
        image = _apply_exif_orientation(source_image, transformations)
    original_image = image.copy()
    original_transformations = list(transformations)
    original_snapshot = _quality_snapshot(image)

    improved_image, preparation = _improve_document_image(
        image,
        original_snapshot["orientation"],
        transformations,
    )
    attempted_transformations = list(transformations)
    target_path = _save_prepared_image(path, improved_image)
    with Image.open(target_path) as prepared_file:
        prepared_snapshot = _quality_snapshot(
            prepared_file.convert("RGB"),
            orientation=preparation["final_orientation"],
        )
    preparation["residual_skew_angle"] = prepared_snapshot["skew_angle"]
    selected_snapshot = prepared_snapshot
    selected_preparation = preparation
    selected_transformations = attempted_transformations
    rolled_back = False

    if _quality_outcome_key(prepared_snapshot["quality"]) >= _quality_outcome_key(
        original_snapshot["quality"]
    ):
        prepared_bytes = target_path.read_bytes()
        _write_prepared_image(target_path, original_image)
        with Image.open(target_path) as rollback_file:
            rollback_snapshot = _quality_snapshot(
                rollback_file.convert("RGB"),
                orientation=original_snapshot["orientation"],
            )
        if _quality_outcome_key(rollback_snapshot["quality"]) <= _quality_outcome_key(
            prepared_snapshot["quality"]
        ):
            selected_snapshot = rollback_snapshot
            selected_preparation = _original_preparation(original_snapshot)
            selected_transformations = [
                *original_transformations,
                "automatic_improvement_rolled_back",
            ]
            rolled_back = True
        else:
            target_path.write_bytes(prepared_bytes)

    quality = _build_quality_report(
        original_size,
        original_snapshot,
        selected_snapshot,
        selected_preparation,
        selected_transformations,
        attempted_prepared_snapshot=prepared_snapshot,
        attempted_transformations=attempted_transformations,
        automatic_improvement_rolled_back=rolled_back,
    )
    return {
        "prepared_path": str(target_path),
        "transformations": selected_transformations,
        "quality": quality,
    }


def _original_preparation(original_snapshot: dict[str, Any]) -> dict[str, Any]:
    orientation = original_snapshot["orientation"]
    skew_angle = original_snapshot["skew_angle"]
    return {
        "initial_orientation": orientation,
        "enhanced_orientation": orientation,
        "final_orientation": orientation,
        "initial_orientation_angle_applied": None,
        "orientation_angle_applied": None,
        "detected_skew_angle": skew_angle,
        "deskew_attempted_angle": None,
        "deskew_angle_applied": None,
        "residual_skew_angle": skew_angle,
    }


def _apply_exif_orientation(source_image, transformations: list[str]):
    from PIL import ImageOps

    transposed = ImageOps.exif_transpose(source_image)
    source_orientation = source_image.getexif().get(274)
    if source_orientation not in (None, 1):
        transformations.append("exif_orientation")
    return transposed.convert("RGB")


def _quality_snapshot(
    image,
    *,
    orientation: dict[str, Any] | None = None,
    skew_angle: float | None = None,
) -> dict[str, Any]:
    metrics = _quality_metrics(image)
    resolved_orientation = orientation or _orientation_analysis(image)
    resolved_skew = (
        skew_angle if skew_angle is not None else _estimate_skew_angle(image)
    )
    quality = dict(metrics)
    quality.update(_edge_touch_metrics(image))
    quality.update(_orientation_quality_fields(resolved_orientation))
    quality.update(
        {
            "detected_skew_angle": resolved_skew,
            "residual_skew_angle": resolved_skew,
        }
    )
    quality.update(_quality_assessment(quality))
    return {
        "metrics": metrics,
        "edge": _edge_quality_fields(quality),
        "orientation": resolved_orientation,
        "skew_angle": resolved_skew,
        "quality": quality,
    }


def _improve_document_image(
    image,
    initial_orientation: dict[str, Any],
    transformations: list[str],
) -> tuple[Any, dict[str, Any]]:
    from PIL import Image, ImageOps

    cropped = _perspective_crop(image)
    if cropped is not None:
        image = cropped
        transformations.append("document_perspective_crop")

    image, initial_rotation = _apply_orientation_correction(
        image,
        initial_orientation,
        transformations,
    )
    image = ImageOps.autocontrast(image, cutoff=1)
    transformations.append("autocontrast")
    image = _upscale_small_image(image, transformations)

    enhanced_orientation = _orientation_analysis(image)
    image, enhanced_rotation = _apply_orientation_correction(
        image,
        enhanced_orientation,
        transformations,
        prefix="post_enhancement_",
    )
    final_orientation = _final_orientation_after_improvement(
        initial_orientation,
        initial_rotation,
        enhanced_orientation,
        enhanced_rotation,
    )
    detected_skew = _estimate_skew_angle(image)
    image, applied, residual, attempted = _verified_deskew_image(
        image,
        detected_skew,
    )
    if applied is not None:
        transformations.append(f"deskew_{applied:+.2f}deg")
    elif attempted is not None:
        transformations.append("deskew_rejected_no_improvement")
    preparation = _preparation_result(
        initial_orientation,
        enhanced_orientation,
        final_orientation,
        initial_rotation,
        enhanced_rotation,
        detected_skew,
        attempted,
        applied,
        residual,
    )
    return image, preparation


def _preparation_result(
    initial_orientation: dict[str, Any],
    enhanced_orientation: dict[str, Any],
    final_orientation: dict[str, Any],
    initial_rotation: int | None,
    enhanced_rotation: int | None,
    detected_skew: float | None,
    attempted: float | None,
    applied: float | None,
    residual: float | None,
) -> dict[str, Any]:
    return {
        "initial_orientation": initial_orientation,
        "enhanced_orientation": enhanced_orientation,
        "final_orientation": final_orientation,
        "initial_orientation_angle_applied": initial_rotation,
        "orientation_angle_applied": enhanced_rotation or initial_rotation,
        "detected_skew_angle": detected_skew,
        "deskew_attempted_angle": attempted,
        "deskew_angle_applied": applied,
        "residual_skew_angle": residual,
    }


def _apply_orientation_correction(
    image,
    orientation: dict[str, Any],
    transformations: list[str],
    *,
    prefix: str = "",
) -> tuple[Any, int | None]:
    rotation = orientation.get("rotation_angle")
    if rotation:
        image = image.rotate(rotation, expand=True)
        name = _orientation_transformation_name(rotation)
        transformations.append(f"{prefix}{name}")
    return image, rotation


def _final_orientation_after_improvement(
    initial: dict[str, Any],
    initial_rotation: int | None,
    enhanced: dict[str, Any],
    enhanced_rotation: int | None,
) -> dict[str, Any]:
    if enhanced_rotation:
        return _resolved_orientation_after_correction(enhanced)
    if initial_rotation or not initial.get("unresolved"):
        return enhanced
    if enhanced.get("unresolved") or _orientation_is_confident_upright(enhanced):
        return enhanced

    unresolved = dict(enhanced)
    unresolved.update(
        {
            "detected_rotation": initial.get("detected_rotation"),
            "unconfirmed_nonzero_hint": True,
            "unresolved_reason": "orientation_ambiguous_after_improvement",
            "unresolved": True,
        }
    )
    return unresolved


def _resolved_orientation_after_correction(
    orientation: dict[str, Any],
) -> dict[str, Any]:
    resolved = dict(orientation)
    resolved.update(
        {
            "rotation_angle": None,
            "unconfirmed_nonzero_hint": False,
            "unresolved_reason": None,
            "unresolved": False,
        }
    )
    return resolved


def _orientation_is_confident_upright(orientation: dict[str, Any]) -> bool:
    confidence = orientation.get("confidence")
    return (
        orientation.get("detected_rotation") == 0
        and confidence is not None
        and float(confidence) >= ORIENTATION_OSD_MIN_CONFIDENCE
    )


def _upscale_small_image(image, transformations: list[str]):
    from PIL import Image

    max_dimension = max(image.size)
    if max_dimension >= 1800:
        return image
    scale = min(2.0, 1800 / max_dimension)
    target_size = (
        max(1, round(image.width * scale)),
        max(1, round(image.height * scale)),
    )
    transformations.append(f"upscale_{scale:.2f}x")
    return image.resize(target_size, Image.Resampling.LANCZOS)


def _build_quality_report(
    original_size: tuple[int, int],
    original_snapshot: dict[str, Any],
    prepared_snapshot: dict[str, Any],
    preparation: dict[str, Any],
    transformations: list[str],
    *,
    attempted_prepared_snapshot: dict[str, Any],
    attempted_transformations: list[str],
    automatic_improvement_rolled_back: bool,
) -> dict[str, Any]:
    original_quality = dict(original_snapshot["quality"])
    original_quality["quality_stage"] = "before_automatic_improvement"
    prepared_quality = dict(prepared_snapshot["quality"])
    prepared_quality["quality_stage"] = "after_automatic_improvement"
    quality = dict(prepared_quality)
    quality.update(
        _original_quality_fields(original_size, original_snapshot["metrics"])
    )
    quality.update(_preparation_quality_fields(preparation))
    final_assessment = _quality_assessment(quality)
    quality.update(final_assessment)
    attempted_prepared_quality = dict(attempted_prepared_snapshot["quality"])
    attempted_prepared_quality["quality_stage"] = (
        "after_automatic_improvement_before_candidate_selection"
    )
    quality.update(
        {
            "original_quality": original_quality,
            "prepared_quality": dict(quality),
            "attempted_prepared_quality": attempted_prepared_quality,
            "initial_quality_insufficient": bool(
                original_quality.get("requires_review")
            ),
            "improvement_applied": bool(attempted_transformations),
            "quality_improved": _quality_rank(final_assessment)
            < _quality_rank(original_quality),
            "improvement_successful": bool(
                original_quality.get("requires_review")
                and not final_assessment.get("requires_review")
            ),
            "automatic_improvement_rolled_back": (
                automatic_improvement_rolled_back
            ),
            "selected_image_variant": (
                "original_after_exif"
                if automatic_improvement_rolled_back
                else "automatically_improved"
            ),
            "selected_transformations": transformations,
            "attempted_transformations": attempted_transformations,
            "final_quality_gate_stage": "after_automatic_improvement",
        }
    )
    quality["prepared_quality"] = _prepared_quality_view(quality)
    return quality


def _preparation_quality_fields(preparation: dict[str, Any]) -> dict[str, Any]:
    final_orientation = preparation["final_orientation"]
    fields = _orientation_quality_fields(final_orientation)
    applied = preparation.get("orientation_angle_applied")
    attempted = preparation.get("deskew_attempted_angle")
    deskew_applied = preparation.get("deskew_angle_applied")
    fields.update(
        {
            "orientation_correction_applied": bool(applied),
            "orientation_angle_applied": applied,
            "quarter_turn_applied": applied in (-90, 90),
            "quarter_turn_angle_applied": (
                applied if applied in (-90, 90) else None
            ),
            "initial_orientation_angle_applied": preparation.get(
                "initial_orientation_angle_applied"
            ),
            "detected_skew_angle": preparation.get("detected_skew_angle"),
            "deskew_attempted_angle": attempted,
            "deskew_angle_applied": deskew_applied,
            "residual_skew_angle": preparation.get("residual_skew_angle"),
            "skew_correction_applied": deskew_applied is not None,
            "skew_correction_rejected": (
                attempted is not None and deskew_applied is None
            ),
        }
    )
    return fields


def _orientation_quality_fields(orientation: dict[str, Any]) -> dict[str, Any]:
    rotation = orientation.get("rotation_angle")
    return {
        "orientation_rotation_detected": orientation.get("detected_rotation"),
        "orientation_detection_method": orientation.get("method"),
        "orientation_confidence": orientation.get("confidence"),
        "orientation_script": orientation.get("script"),
        "orientation_error": orientation.get("error"),
        "orientation_unconfirmed_nonzero_hint": orientation.get(
            "unconfirmed_nonzero_hint", False
        ),
        "orientation_unconfirmed_upside_down_hint": orientation.get(
            "unconfirmed_upside_down_hint", False
        ),
        "orientation_upside_down_confirmation_attempted": orientation.get(
            "upside_down_confirmation_attempted", False
        ),
        "orientation_upside_down_confirmation_confidence": orientation.get(
            "upside_down_confirmation_confidence"
        ),
        "orientation_upside_down_confirmation_error": orientation.get(
            "upside_down_confirmation_error"
        ),
        "orientation_upside_down_confirmed": orientation.get(
            "upside_down_confirmed", False
        ),
        "orientation_unresolved_reason": orientation.get("unresolved_reason"),
        "orientation_unresolved": orientation.get("unresolved", False),
        "quarter_turn_detected": orientation.get("quarter_turn_detected", False),
        "quarter_turn_applied": rotation in (-90, 90),
        "quarter_turn_angle_applied": rotation if rotation in (-90, 90) else None,
    }


def _edge_quality_fields(quality: dict[str, Any]) -> dict[str, Any]:
    names = (
        "edge_touch_ratio",
        "edge_touch_count",
        "text_block_count",
        "edge_margin_pixels",
        "possible_cropped_document",
        "edge_touch_metrics_available",
    )
    return {name: quality.get(name) for name in names if name in quality}


def _prepared_quality_view(quality: dict[str, Any]) -> dict[str, Any]:
    excluded = {
        "original_quality",
        "prepared_quality",
        "attempted_prepared_quality",
        "initial_quality_insufficient",
        "improvement_applied",
        "quality_improved",
        "improvement_successful",
        "automatic_improvement_rolled_back",
        "selected_image_variant",
        "selected_transformations",
        "attempted_transformations",
        "final_quality_gate_stage",
    }
    prepared = {
        key: value
        for key, value in quality.items()
        if key not in excluded and not key.startswith("original_")
    }
    prepared["quality_stage"] = "after_automatic_improvement"
    return prepared


def _quality_rank(quality: dict[str, Any]) -> int:
    decision = quality.get("quality_decision")
    return {"accept": 0, "review": 1, "reject": 2}.get(str(decision), 3)


def _quality_outcome_key(quality: dict[str, Any]) -> tuple[int, int, int]:
    return (
        _quality_rank(quality),
        int(quality.get("critical_error_count") or 0),
        int(quality.get("warning_count") or 0),
    )


def _save_prepared_image(path: Path, image) -> Path:
    target_dir = Path(settings.uploaded_invoices_dir) / ".prepared"
    target_dir.mkdir(parents=True, exist_ok=True)
    target_path = target_dir / f"{path.stem}-{uuid4().hex[:10]}.jpg"
    _write_prepared_image(target_path, image)
    return target_path


def _write_prepared_image(target_path: Path, image) -> None:
    image.save(target_path, format="JPEG", quality=95, optimize=True)


def _original_quality_fields(
    original_size: tuple[int, int],
    original_metrics: dict[str, Any],
) -> dict[str, Any]:
    fields: dict[str, Any] = {
        "original_width": original_size[0],
        "original_height": original_size[1],
        "original_short_side": min(original_size),
        "original_long_side": max(original_size),
    }
    for name in (
        "blur_score",
        "glare_ratio",
        "dark_ratio",
        "clipping_ratio",
        "text_coverage_ratio",
        "brightness_mean",
        "brightness_std",
        "foreground_contrast",
    ):
        if name in original_metrics:
            fields[f"original_{name}"] = original_metrics[name]
    return fields


def _perspective_crop(image):
    try:
        import cv2
        import numpy as np
        from PIL import Image
    except ImportError:
        return None

    array = np.array(image)
    gray = cv2.cvtColor(array, cv2.COLOR_RGB2GRAY)
    blurred = cv2.GaussianBlur(gray, (5, 5), 0)
    edges = cv2.Canny(blurred, 50, 150)
    contours, _ = cv2.findContours(edges, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
    image_area = image.width * image.height
    for contour in sorted(contours, key=cv2.contourArea, reverse=True)[:8]:
        if cv2.contourArea(contour) < image_area * 0.45:
            continue
        perimeter = cv2.arcLength(contour, True)
        polygon = cv2.approxPolyDP(contour, 0.02 * perimeter, True)
        if len(polygon) != 4:
            continue
        points = _order_points(polygon.reshape(4, 2).astype("float32"))
        top_left, top_right, bottom_right, bottom_left = points
        width = int(
            max(
                _distance(bottom_right, bottom_left),
                _distance(top_right, top_left),
            )
        )
        height = int(
            max(
                _distance(top_right, bottom_right),
                _distance(top_left, bottom_left),
            )
        )
        if width < 200 or height < 200:
            continue
        destination = np.array(
            [[0, 0], [width - 1, 0], [width - 1, height - 1], [0, height - 1]],
            dtype="float32",
        )
        transform = cv2.getPerspectiveTransform(points, destination)
        warped = cv2.warpPerspective(array, transform, (width, height))
        return Image.fromarray(warped)
    return None


def _quality_metrics(image) -> dict[str, Any]:
    try:
        import cv2
        import numpy as np
    except ImportError:
        return {
            "width": image.width,
            "height": image.height,
            "quality_metrics_available": False,
        }

    gray = cv2.cvtColor(np.array(image), cv2.COLOR_RGB2GRAY)
    blur_score = float(cv2.Laplacian(gray, cv2.CV_64F).var())
    glare_ratio = float((gray >= 248).mean())
    dark_ratio = float((gray <= 12).mean())
    clipping_ratio = float(((gray <= 4) | (gray >= 251)).mean())
    text_coverage_ratio = float((gray < 200).mean())
    brightness_mean = float(gray.mean())
    brightness_std = float(gray.std())
    foreground_contrast = _foreground_contrast(gray, brightness_mean)
    possible_quarter_turn = _quarter_turn_evidence(gray)
    return {
        "width": image.width,
        "height": image.height,
        "blur_score": round(blur_score, 2),
        "glare_ratio": round(glare_ratio, 4),
        "dark_ratio": round(dark_ratio, 4),
        "clipping_ratio": round(clipping_ratio, 4),
        "text_coverage_ratio": round(text_coverage_ratio, 4),
        "brightness_mean": round(brightness_mean, 2),
        "brightness_std": round(brightness_std, 2),
        "foreground_contrast": round(foreground_contrast, 2),
        "possible_quarter_turn": possible_quarter_turn,
        "quality_metrics_available": True,
    }


def _foreground_contrast(gray, brightness_mean: float) -> float:
    import numpy as np

    flat = gray.reshape(-1)
    sample_count = max(1, round(flat.size * 0.01))
    darkest = np.partition(flat, sample_count - 1)[:sample_count]
    return max(0.0, brightness_mean - float(darkest.mean()))


def _quarter_turn_rotation(image) -> int | None:
    return _orientation_analysis(image)["rotation_angle"]


def _orientation_analysis(image) -> dict[str, Any]:
    try:
        import cv2
        import numpy as np
    except ImportError:
        return _empty_orientation_analysis(error="OpenCV недоступен.")

    gray = cv2.cvtColor(np.array(image), cv2.COLOR_RGB2GRAY)
    landscape = image.width >= image.height * QUARTER_TURN_MIN_ASPECT_RATIO
    structural_quarter_turn = landscape and _quarter_turn_evidence(gray)

    osd = _tesseract_orientation(image)
    osd_rotation = osd.get("rotate_clockwise")
    confidence = osd.get("confidence")
    valid_rotation = osd_rotation in (0, 90, 180, 270)
    confident = (
        valid_rotation
        and confidence is not None
        and float(confidence) >= ORIENTATION_OSD_MIN_CONFIDENCE
    )
    confirmed_upside_down = False
    confirmation = _empty_upside_down_confirmation()
    if osd_rotation == 180 and not confident:
        confirmation = _confirm_low_confidence_upside_down(
            image,
            confidence,
        )
        confirmed_upside_down = confirmation["confirmed"]

    confident_rotation = confident or confirmed_upside_down
    confident_quarter_turn = confident and osd_rotation in (90, 270)
    unconfirmed_quarter_turn_hint = osd_rotation in (90, 270) and not confident
    unconfirmed_upside_down_hint = (
        osd_rotation == 180 and not confident_rotation
    )

    rotation_angle = None
    if confident_rotation and (
        osd_rotation == 180
        or not structural_quarter_turn
        or confident_quarter_turn
    ):
        rotation_angle = _pil_rotation_from_osd(osd_rotation)

    quarter_turn_detected = structural_quarter_turn or osd_rotation in (90, 270)
    unresolved = unconfirmed_quarter_turn_hint or (
        structural_quarter_turn and not confident_quarter_turn
    )
    unresolved_reason = None
    if unconfirmed_quarter_turn_hint:
        unresolved_reason = "nonzero_osd_below_confidence"
    elif structural_quarter_turn and not confident_quarter_turn:
        unresolved_reason = "sideways_structure_without_confident_direction"

    return {
        "rotation_angle": rotation_angle,
        "detected_rotation": osd_rotation if valid_rotation else None,
        "method": "tesseract_osd",
        "confidence": confidence,
        "script": osd.get("script"),
        "error": osd.get("error"),
        "quarter_turn_detected": quarter_turn_detected,
        "unconfirmed_nonzero_hint": unconfirmed_quarter_turn_hint,
        "unconfirmed_upside_down_hint": unconfirmed_upside_down_hint,
        "upside_down_confirmation_attempted": confirmation["attempted"],
        "upside_down_confirmation_confidence": confirmation["confidence"],
        "upside_down_confirmation_error": confirmation["error"],
        "upside_down_confirmed": confirmed_upside_down,
        "unresolved_reason": unresolved_reason,
        "unresolved": unresolved,
    }


def _confirm_low_confidence_upside_down(
    image,
    original_confidence: float | None,
) -> dict[str, Any]:
    rotated = image.rotate(180, expand=True)
    candidate = _tesseract_orientation(rotated)
    candidate_rotation = candidate.get("rotate_clockwise")
    candidate_confidence = candidate.get("confidence")
    if candidate_confidence is None:
        return {
            "attempted": True,
            "confirmed": False,
            "confidence": None,
            "error": candidate.get("error"),
        }

    original_value = float(original_confidence or 0.0)
    candidate_value = float(candidate_confidence)
    required_confidence = max(
        ORIENTATION_180_CONFIRMATION_MIN_CONFIDENCE,
        original_value + ORIENTATION_180_CONFIRMATION_GAIN,
    )
    confirmed = (
        candidate_rotation == 0
        and candidate_value >= required_confidence
    )
    return {
        "attempted": True,
        "confirmed": confirmed,
        "confidence": candidate_value,
        "error": candidate.get("error"),
    }


def _empty_upside_down_confirmation() -> dict[str, Any]:
    return {
        "attempted": False,
        "confirmed": False,
        "confidence": None,
        "error": None,
    }


def _empty_orientation_analysis(error: str | None = None) -> dict[str, Any]:
    return {
        "rotation_angle": None,
        "detected_rotation": None,
        "method": None,
        "confidence": None,
        "script": None,
        "error": error,
        "quarter_turn_detected": False,
        "unconfirmed_nonzero_hint": False,
        "unconfirmed_upside_down_hint": False,
        "upside_down_confirmation_attempted": False,
        "upside_down_confirmation_confidence": None,
        "upside_down_confirmation_error": None,
        "upside_down_confirmed": False,
        "unresolved_reason": None,
        "unresolved": False,
    }


def _tesseract_orientation(image) -> dict[str, Any]:
    try:
        import pytesseract
        from PIL import ImageOps
    except ImportError:
        return {
            "rotate_clockwise": None,
            "confidence": None,
            "script": None,
            "error": "Tesseract OSD недоступен.",
        }

    try:
        analysis_image = ImageOps.autocontrast(image.convert("L"), cutoff=1)
        analysis_image = _resize_orientation_image(analysis_image)
        result = pytesseract.image_to_osd(
            analysis_image,
            output_type=pytesseract.Output.DICT,
            config="--psm 0",
        )
        rotate_clockwise = int(result.get("rotate") or 0) % 360
        confidence = float(result.get("orientation_conf") or 0.0)
        return {
            "rotate_clockwise": rotate_clockwise,
            "confidence": round(confidence, 2),
            "script": str(result.get("script") or "").strip() or None,
            "error": None,
        }
    except Exception as exc:  # noqa: BLE001 - ambiguity is handled as rejection
        return {
            "rotate_clockwise": None,
            "confidence": None,
            "script": None,
            "error": f"Не удалось определить ориентацию: {type(exc).__name__}.",
        }


def _resize_orientation_image(image):
    from PIL import Image

    width, height = image.size
    largest = max(width, height)
    smallest = min(width, height)
    scale = 1.0
    if largest > ORIENTATION_OSD_MAX_DIMENSION:
        scale = ORIENTATION_OSD_MAX_DIMENSION / largest
    elif smallest < ORIENTATION_OSD_MIN_DIMENSION:
        scale = min(2.0, ORIENTATION_OSD_MIN_DIMENSION / max(smallest, 1))
    if abs(scale - 1.0) < 0.001:
        return image
    return image.resize(
        (max(1, round(width * scale)), max(1, round(height * scale))),
        Image.Resampling.LANCZOS,
    )


def _pil_rotation_from_osd(rotate_clockwise: int | None) -> int | None:
    mapping = {90: -90, 180: 180, 270: 90}
    return mapping.get(rotate_clockwise)


def _orientation_transformation_name(rotation: int) -> str:
    names = {
        90: "auto_rotate_90_ccw",
        -90: "auto_rotate_90_cw",
        180: "auto_rotate_180",
    }
    return names.get(rotation, f"auto_rotate_{rotation:+d}")


def _quarter_turn_evidence(gray) -> bool:
    import cv2
    import numpy as np

    height, width = gray.shape
    if width < height * QUARTER_TURN_MIN_ASPECT_RATIO:
        return False
    dark = gray < 180
    horizontal_score = float(np.std(np.mean(dark, axis=1)))
    vertical_score = float(np.std(np.mean(dark, axis=0)))
    if horizontal_score <= 0.0:
        return False
    if vertical_score < horizontal_score * QUARTER_TURN_MIN_PROJECTION_RATIO:
        return False

    analysis_gray = _resize_for_analysis(gray, 1600)
    _, binary = cv2.threshold(
        analysis_gray,
        0,
        255,
        cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU,
    )
    text_mask = _remove_long_document_lines(binary)
    edges = cv2.Canny(text_mask, 50, 150, apertureSize=3)
    short_side = min(analysis_gray.shape)
    lines = cv2.HoughLinesP(
        edges,
        1,
        np.pi / 180,
        threshold=max(30, short_side // 35),
        minLineLength=max(35, short_side // 18),
        maxLineGap=max(10, short_side // 60),
    )
    horizontal_weight, vertical_weight = _axis_line_weights(lines)
    minimum_vertical_weight = max(250.0, short_side * 1.5)
    return (
        vertical_weight >= minimum_vertical_weight
        and vertical_weight
        > max(horizontal_weight * QUARTER_TURN_MIN_LINE_RATIO, 0.0)
    )


def _axis_line_weights(lines) -> tuple[float, float]:
    if lines is None:
        return 0.0, 0.0

    import math

    horizontal_weight = 0.0
    vertical_weight = 0.0
    for x1, y1, x2, y2 in lines[:, 0]:
        angle = abs(math.degrees(math.atan2(y2 - y1, x2 - x1)))
        axis_angle = min(angle, 180.0 - angle)
        length = math.hypot(x2 - x1, y2 - y1)
        if axis_angle <= QUARTER_TURN_MAX_AXIS_ANGLE:
            horizontal_weight += length
        elif axis_angle >= QUARTER_TURN_MIN_AXIS_ANGLE:
            vertical_weight += length
    return horizontal_weight, vertical_weight


def _estimate_skew_angle(image) -> float | None:
    try:
        import cv2
        import numpy as np
    except ImportError:
        return None

    gray = cv2.cvtColor(np.array(image), cv2.COLOR_RGB2GRAY)
    gray = _resize_for_analysis(gray, 1600)
    blurred = cv2.GaussianBlur(gray, (3, 3), 0)
    edges = cv2.Canny(blurred, 50, 150, apertureSize=3)
    short_side = min(gray.shape)
    lines = cv2.HoughLinesP(
        edges,
        1,
        np.pi / 180,
        threshold=max(30, short_side // 35),
        minLineLength=max(35, short_side // 18),
        maxLineGap=max(10, short_side // 60),
    )
    weighted_angles = _horizontal_line_angles(lines)
    if weighted_angles:
        return round(_weighted_median(weighted_angles), 2)
    return _foreground_skew_angle(gray)


def _resize_for_analysis(gray, max_dimension: int):
    import cv2

    height, width = gray.shape
    scale = min(1.0, max_dimension / max(height, width))
    if scale == 1.0:
        return gray
    return cv2.resize(
        gray,
        (max(1, round(width * scale)), max(1, round(height * scale))),
        interpolation=cv2.INTER_AREA,
    )


def _horizontal_line_angles(lines) -> list[tuple[float, float]]:
    if lines is None:
        return []

    import math

    angles: list[tuple[float, float]] = []
    for x1, y1, x2, y2 in lines[:, 0]:
        angle = math.degrees(math.atan2(y2 - y1, x2 - x1))
        while angle <= -90:
            angle += 180
        while angle > 90:
            angle -= 180
        if abs(angle) <= 30:
            length = math.hypot(x2 - x1, y2 - y1)
            angles.append((angle, length))
    return angles


def _weighted_median(values: list[tuple[float, float]]) -> float:
    ordered = sorted(values, key=lambda item: item[0])
    halfway = sum(weight for _, weight in ordered) / 2
    accumulated = 0.0
    result = ordered[-1][0]
    for value, weight in ordered:
        accumulated += weight
        if accumulated >= halfway:
            result = value
            break
    return result


def _foreground_skew_angle(gray) -> float | None:
    import cv2
    import numpy as np

    _, threshold = cv2.threshold(
        gray,
        0,
        255,
        cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU,
    )
    border = max(2, round(min(gray.shape) * 0.01))
    threshold[:border, :] = 0
    threshold[-border:, :] = 0
    threshold[:, :border] = 0
    threshold[:, -border:] = 0
    points = cv2.findNonZero(threshold)
    if points is None or len(points) < 50:
        return None
    angle = float(cv2.minAreaRect(points)[-1])
    if angle > 45:
        angle -= 90
    correction_angle = -angle
    if abs(correction_angle) > 30:
        return None
    return round(correction_angle, 2)


def _deskew_image(image, correction_angle: float | None = None):
    try:
        import cv2
        import numpy as np
        from PIL import Image
    except ImportError:
        return image, None

    angle = correction_angle
    if angle is None or abs(angle) < DESKEW_MIN_ANGLE:
        return image, None
    if abs(angle) > DESKEW_MAX_ANGLE:
        return image, None

    center = (image.width / 2, image.height / 2)
    matrix = cv2.getRotationMatrix2D(center, angle, 1.0)
    rotated = cv2.warpAffine(
        np.array(image),
        matrix,
        (image.width, image.height),
        flags=cv2.INTER_CUBIC,
        borderMode=cv2.BORDER_REPLICATE,
    )
    return Image.fromarray(rotated), round(angle, 2)


def _verified_deskew_image(
    image,
    detected_angle: float | None,
):
    candidate, attempted_angle = _deskew_image(image, detected_angle)
    if attempted_angle is None:
        return image, None, detected_angle, None

    candidate_residual = _estimate_skew_angle(candidate)
    if _deskew_improves(detected_angle, candidate_residual):
        return candidate, attempted_angle, candidate_residual, attempted_angle
    return image, None, detected_angle, attempted_angle


def _deskew_improves(
    detected_angle: float | None,
    residual_angle: float | None,
) -> bool:
    if detected_angle is None or residual_angle is None:
        return False
    original = abs(float(detected_angle))
    residual = abs(float(residual_angle))
    return residual + DESKEW_IMPROVEMENT_EPSILON < original


def _edge_touch_metrics(image) -> dict[str, Any]:
    try:
        import cv2
        import numpy as np
    except ImportError:
        return {
            "edge_touch_ratio": 0.0,
            "edge_touch_count": 0,
            "text_block_count": 0,
            "edge_touch_metrics_available": False,
        }

    gray = cv2.cvtColor(np.array(image), cv2.COLOR_RGB2GRAY)
    gray = _resize_for_analysis(gray, 1800)
    _, binary = cv2.threshold(
        gray,
        0,
        255,
        cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU,
    )
    text_mask = _remove_long_document_lines(binary)
    height, width = text_mask.shape
    grouping_kernel = cv2.getStructuringElement(
        cv2.MORPH_RECT,
        (max(5, width // 60), max(2, height // 600)),
    )
    grouped = cv2.dilate(text_mask, grouping_kernel, iterations=1)
    _, _, stats, _ = cv2.connectedComponentsWithStats(grouped, connectivity=8)
    margin = max(5, round(min(width, height) * EDGE_MARGIN_RATIO))
    block_count, touching_count = _count_edge_touching_blocks(
        stats,
        width,
        height,
        margin,
    )
    ratio = touching_count / block_count if block_count else 0.0
    return {
        "edge_touch_ratio": round(float(ratio), 4),
        "edge_touch_count": touching_count,
        "text_block_count": block_count,
        "edge_margin_pixels": margin,
        "possible_cropped_document": (
            touching_count >= MIN_EDGE_TOUCH_BLOCKS
            and ratio >= HIGH_EDGE_TOUCH_RATIO
        ),
        "edge_touch_metrics_available": True,
    }


def _remove_long_document_lines(binary):
    import cv2

    height, width = binary.shape
    horizontal_kernel = cv2.getStructuringElement(
        cv2.MORPH_RECT,
        (max(20, width // 18), 1),
    )
    vertical_kernel = cv2.getStructuringElement(
        cv2.MORPH_RECT,
        (1, max(20, height // 18)),
    )
    horizontal = cv2.morphologyEx(binary, cv2.MORPH_OPEN, horizontal_kernel)
    vertical = cv2.morphologyEx(binary, cv2.MORPH_OPEN, vertical_kernel)
    lines = cv2.bitwise_or(horizontal, vertical)
    return cv2.bitwise_and(binary, cv2.bitwise_not(lines))


def _count_edge_touching_blocks(
    stats,
    image_width: int,
    image_height: int,
    margin: int,
) -> tuple[int, int]:
    image_area = image_width * image_height
    min_area = max(20, round(image_area * 0.000005))
    max_area = round(image_area * 0.03)
    block_count = 0
    touching_count = 0
    for x, y, width, height, area in stats[1:]:
        valid = (
            min_area <= area <= max_area
            and width >= 4
            and height >= 4
            and width <= image_width * 0.90
            and height <= image_height * 0.15
        )
        if valid:
            block_count += 1
            if _block_touches_edge(
                x,
                y,
                width,
                height,
                image_width,
                image_height,
                margin,
            ):
                touching_count += 1
    return block_count, touching_count


def _block_touches_edge(
    x: int,
    y: int,
    width: int,
    height: int,
    image_width: int,
    image_height: int,
    margin: int,
) -> bool:
    return (
        x <= margin
        or y <= margin
        or x + width >= image_width - margin
        or y + height >= image_height - margin
    )


def _quality_assessment(quality: dict[str, Any]) -> dict[str, Any]:
    if not quality.get("quality_metrics_available"):
        return _empty_quality_assessment()

    warnings: list[tuple[str, str]] = []
    critical_errors: list[tuple[str, str]] = []
    _assess_resolution(quality, warnings, critical_errors)
    _assess_blur(quality, warnings, critical_errors)
    _assess_lighting(quality, warnings, critical_errors)
    _assess_orientation(quality, warnings, critical_errors)
    _assess_skew(quality, warnings, critical_errors)
    _assess_edge_touch(quality, warnings, critical_errors)
    _assess_text_coverage(quality, warnings, critical_errors)

    warning_codes = [code for code, _ in warnings]
    critical_codes = [code for code, _ in critical_errors]
    review_reasons = [reason for _, reason in critical_errors + warnings]
    stop_reasons = [reason for _, reason in critical_errors]
    if len(warnings) >= 2:
        labels = "; ".join(reason for _, reason in warnings)
        stop_reasons.append(f"Обнаружено несколько проблем качества: {labels}")
    stop_recommended = bool(critical_errors) or len(warnings) >= 2
    return {
        "warning_codes": warning_codes,
        "critical_error_codes": critical_codes,
        "warning_count": len(warnings),
        "critical_error_count": len(critical_errors),
        "review_reasons": review_reasons,
        "stop_reasons": stop_reasons,
        "requires_review": bool(review_reasons),
        "stop_recommended": stop_recommended,
        "quality_decision": "reject"
        if stop_recommended
        else ("review" if warnings else "accept"),
    }


def _empty_quality_assessment() -> dict[str, Any]:
    return {
        "warning_codes": [],
        "critical_error_codes": [],
        "warning_count": 0,
        "critical_error_count": 0,
        "review_reasons": [],
        "stop_reasons": [],
        "requires_review": False,
        "stop_recommended": False,
        "quality_decision": "unavailable",
    }


def _assess_resolution(quality, warnings, critical_errors) -> None:
    width = int(quality.get("width") or 0)
    height = int(quality.get("height") or 0)
    current_short_side = min(width, height) if width and height else 0
    original_short_side = int(quality.get("original_short_side") or 0)
    short_side = int(
        original_short_side
        or quality.get("short_side")
        or current_short_side
        or 0
    )
    if short_side and short_side < CRITICAL_QUALITY_SHORT_SIDE:
        critical_errors.append(
            (
                "critical_low_resolution",
                "Критически низкое исходное разрешение изображения: короткая "
                f"сторона {short_side}px, требуется не менее "
                f"{CRITICAL_QUALITY_SHORT_SIDE}px.",
            )
        )
    elif short_side and short_side < MIN_QUALITY_SHORT_SIDE:
        qualifier = (
            "Очень низкое"
            if short_side < LOW_RESOLUTION_SHORT_SIDE
            else "Низкое"
        )
        warnings.append(
            (
                "low_resolution",
                f"{qualifier} разрешение изображения: короткая сторона "
                f"{short_side}px, рекомендуется от {MIN_QUALITY_SHORT_SIDE}px.",
            )
        )


def _assess_blur(quality, warnings, critical_errors) -> None:
    coverage = float(
        quality.get(
            "text_coverage_ratio",
            quality.get("original_text_coverage_ratio", 0.0),
        )
    )
    if coverage < CRITICAL_TEXT_COVERAGE:
        return
    score = float(quality.get("blur_score", quality.get("original_blur_score", 0.0)))
    if score < CRITICAL_BLUR_SCORE:
        critical_errors.append(
            ("critical_blur", "Фотография сильно размыта или находится не в фокусе.")
        )
    elif score < LOW_BLUR_SCORE:
        warnings.append(
            ("blur", "Низкая резкость фотографии, текст может распознаться с ошибками.")
        )


def _assess_lighting(quality, warnings, critical_errors) -> None:
    glare = float(quality.get("glare_ratio", quality.get("original_glare_ratio", 0.0)))
    dark = float(quality.get("dark_ratio", quality.get("original_dark_ratio", 0.0)))
    clipping = float(
        quality.get("clipping_ratio", quality.get("original_clipping_ratio", 0.0))
    )
    mean_value = quality.get("brightness_mean", quality.get("original_brightness_mean"))
    deviation_value = quality.get(
        "brightness_std",
        quality.get("original_brightness_std"),
    )
    contrast_value = quality.get(
        "foreground_contrast",
        quality.get("original_foreground_contrast"),
    )
    mean = float(mean_value) if mean_value is not None else None
    deviation = float(deviation_value) if deviation_value is not None else None
    foreground_contrast = (
        float(contrast_value) if contrast_value is not None else None
    )
    critically_dark = dark > CRITICAL_DARK_RATIO or (
        mean is not None and mean < CRITICAL_BRIGHTNESS_MEAN
    )
    critically_bright = (
        mean is not None
        and deviation is not None
        and glare > CRITICAL_GLARE_RATIO
        and clipping > CRITICAL_CLIPPING_RATIO
        and mean > CRITICAL_HIGH_BRIGHTNESS_MEAN
        and deviation < CRITICAL_BRIGHTNESS_STD
        and (
            foreground_contrast is None
            or foreground_contrast < CRITICAL_FOREGROUND_CONTRAST
        )
    )
    poorly_lit = dark > HIGH_DARK_RATIO or (
        mean is not None and mean < LOW_BRIGHTNESS_MEAN
    )
    low_contrast_overexposure = (
        mean is not None
        and deviation is not None
        and glare > HIGH_GLARE_RATIO
        and clipping > HIGH_CLIPPING_RATIO
        and mean > HIGH_BRIGHTNESS_MEAN
        and deviation < LOW_BRIGHTNESS_STD
        and (
            foreground_contrast is None
            or foreground_contrast < LOW_FOREGROUND_CONTRAST
        )
    )
    if critically_dark or critically_bright:
        critical_errors.append(
            ("critical_lighting", "Освещение скрывает значительную часть документа.")
        )
    elif poorly_lit or low_contrast_overexposure:
        warnings.append(
            ("bad_lighting", "Есть сильный пересвет или слишком тёмные области.")
        )


def _assess_orientation(quality, warnings, critical_errors) -> None:
    if not quality.get("orientation_unresolved"):
        return
    confidence_value = quality.get("orientation_confidence")
    confidence = (
        float(confidence_value) if confidence_value is not None else None
    )
    confidence_suffix = (
        f" Уверенность определения: {confidence:.1f}."
        if confidence is not None
        else ""
    )
    detected_rotation = quality.get("orientation_rotation_detected")
    rotation_suffix = (
        f" Предполагаемый поворот: {detected_rotation}°."
        if detected_rotation in (90, 180, 270)
        else ""
    )
    critical_errors.append(
        (
            "critical_orientation_unresolved",
            "Ориентацию документа определить надёжно не удалось. Поверните "
            "изображение вертикально, убедитесь, что текст не перевёрнут, "
            f"или перефотографируйте документ.{rotation_suffix}"
            f"{confidence_suffix}",
        )
    )


def _assess_skew(quality, warnings, critical_errors) -> None:
    detected = abs(float(quality.get("detected_skew_angle") or 0.0))
    residual_value = quality.get("residual_skew_angle")
    residual = (
        abs(float(residual_value))
        if residual_value is not None
        else detected
    )
    if residual >= SKEW_CRITICAL_ANGLE:
        critical_errors.append(
            (
                "critical_skew",
                f"После подготовки документ сильно перекошен: примерно {residual:.1f}°.",
            )
        )
    elif residual >= SKEW_WARNING_ANGLE:
        correction_rejected = bool(quality.get("skew_correction_rejected"))
        suffix = (
            " Автоматическое выравнивание отменено, поскольку не улучшило результат."
            if correction_rejected
            else ""
        )
        warnings.append(
            (
                "excessive_skew",
                f"Документ заметно наклонён: примерно {residual:.1f}°.{suffix}",
            )
        )


def _assess_edge_touch(quality, warnings, critical_errors) -> None:
    ratio = float(quality.get("edge_touch_ratio") or 0.0)
    count = int(quality.get("edge_touch_count") or 0)
    if count < MIN_EDGE_TOUCH_BLOCKS:
        return
    if ratio >= CRITICAL_EDGE_TOUCH_RATIO:
        critical_errors.append(
            (
                "critical_edge_touch",
                "Текстовые блоки массово упираются в края кадра; документ, вероятно, обрезан.",
            )
        )
    elif ratio >= HIGH_EDGE_TOUCH_RATIO:
        warnings.append(
            (
                "edge_touch",
                "Часть текста находится вплотную к краю кадра; возможна обрезка документа.",
            )
        )


def _assess_text_coverage(quality, warnings, critical_errors) -> None:
    coverage = float(quality.get("text_coverage_ratio") or 0.0)
    if coverage < CRITICAL_TEXT_COVERAGE:
        critical_errors.append(
            ("critical_low_text_coverage", "На изображении слишком мало текстовых областей.")
        )
    elif coverage < LOW_TEXT_COVERAGE:
        warnings.append(
            ("low_text_coverage", "На изображении обнаружено мало текстовых областей.")
        )


def _quality_review_reasons(quality: dict[str, Any]) -> tuple[list[str], list[str]]:
    assessment = _quality_assessment(quality)
    return assessment["review_reasons"], assessment["stop_reasons"]


def _order_points(points):
    import numpy as np

    ordered = np.zeros((4, 2), dtype="float32")
    sums = points.sum(axis=1)
    differences = np.diff(points, axis=1)
    ordered[0] = points[sums.argmin()]
    ordered[2] = points[sums.argmax()]
    ordered[1] = points[differences.argmin()]
    ordered[3] = points[differences.argmax()]
    return ordered


def _distance(first, second) -> float:
    import numpy as np

    return float(np.linalg.norm(first - second))
