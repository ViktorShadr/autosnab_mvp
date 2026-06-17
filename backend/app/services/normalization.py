import re


def normalize_product_name(value: str | None) -> str:
    text = (value or "").lower().replace("ё", "е")
    text = re.sub(r"[^a-zа-я0-9%.,\-\s]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    replacements = {
        "гр.": "г",
        "гр": "г",
        "килограмм": "кг",
        "литр": "л",
        "штук": "шт",
    }
    for old, new in replacements.items():
        text = text.replace(old, new)
    return text


def product_similarity(left: str | None, right: str | None) -> float:
    left_norm = normalize_product_name(left)
    right_norm = normalize_product_name(right)
    if not left_norm or not right_norm:
        return 0.0
    left_tokens = set(left_norm.split())
    right_tokens = set(right_norm.split())
    token_score = len(left_tokens & right_tokens) / max(len(left_tokens | right_tokens), 1)
    substring_score = 1.0 if left_norm in right_norm or right_norm in left_norm else 0.0
    return max(token_score, substring_score)
