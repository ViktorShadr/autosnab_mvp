import base64
import json

import pytest

from app.services import google_service_account_service

# Throwaway RSA key generated for tests only -- never a real credential.
FAKE_PRIVATE_KEY_PEM = """-----BEGIN RSA PRIVATE KEY-----
MIIEqQIBAAKCAQEAlQbDjgg/aiXK2Ag/7YRaRnKcQuVEkrdezzmS7I7rL9DwnsLx
RyuJZ05CJgpEVMitcu20LyPAejnzS7/ipfq+Uu7jGg+7zfCEiGCUpfmfTlYQMbir
rDPHmYDbvZOl4GYIUYwk+qgEmpnAh43NZFLfbMD9jgYKeKK1++6/JWxyx9HDsSEE
eI77megKNlU7FnGCOiNZDIoaKGJmkc6Wa8a3rOMFTlSytmnsQY0SU8Hat4YsqKKa
x4Rlioe1M3zn5bwN3uIIF+RhwOtgJBBmlrnT7VDbTBd/Az+tVekcHWd0aDzoTRS9
1EshllUGbm/qhFpzsPj5CRYEn/YmSkkCSCuPsQIDAQABAoIBAQCExbryzwxYsQUR
BgCWx8V6YGAyBXvbz32r2Jq7IfYN6vSGLh6zDunjXUj4BUut0gEelQNkwFCbVQgb
ZAE1abmpv+Yb8Qqcx3381zd4zHaPX4QcGHDzAksBy1l7hJFT5PPiW58SpyE68GMl
IkRs7pzakvMUVvN7WVOG04DOaGN7RXcgS3xOljsb30e+KUV3rySPH/uu+21rUc0B
69svdA1vjUaRx9k26gADw/FfKh37wo6Q68iI1R1YKqjRoPOyawsfzRIdvBRFsrKm
UGHHqiVQWt+iA0nxjpSVwTJNbqMV/5+wLNPZOMQAnlAbMd+SxixyCW9vTvdIoG3b
2CxdRnqFAoGJAJ5uV7yFnGBwrd8yiynTYo0fMEG6KbZ3+32jFNr7zE6oHzOtPJ5w
RV+cdCK6GVGNS6CSxW6rgnazyIAK6Q0x4GjIcA2+h5qGX7CaQKxHvr7MoCmGJnE/
wWu6bJghLfbGV7dcU1jyaqwJwkLmNPsAe5r1rQ44cQjaz0yd8JTfFlsBAGAmxY+Q
12MCeQDwzbm6TKtnycf9ef+6ETqK8GnR1KfZodour03RXVZzDB4T4NdXD+FzRUFb
wfcDOAbZUnvFTnKdAl7XTEJm8yxj32WrA8KQvVrVTNsjE7Y58//d5Ao4yRbGFF4A
D1ky8yQdfPG0M95gXOvTLkL8I0zhpypF1maT2tsCgYh1b69jU9rldcC8eJfFSiZ8
GwlHPzpaQjfOGkuEQy9fgqmWQax0eR5DUBKaBz5rQAQ2I3VrooBTgtJ1byDvIfCJ
W0IMPhYASei2XLDhw1C117JE9WabfbnfI9IJNlb+3Gj6xtoVTaQaoCU6N7A/+kyl
QcSkjNvkx2TwEwbZI0BL9sMTgsngsGmnAnhsqCfaTKY7Wu2HDvm5d/S2pOza5d4n
ccUFs8ylYDyWBS29QoNooZ3VabaoNMnFBg7xGSsISPGmr18kPyDnW2r4VeGGXVf5
/7dw8BEhrs9XLyaRdUi3fuVr09zmogZZ2yS8uZhG+/CoAsXWsNVA+JzEZa3JfYkj
xmkCgYhCVbM4JKlk+55UMOley7tCjHxWEcogCVnVYbW+hMcdyiMJUgyfW+1YwYAN
ErLEgEWS2DQiGCgOwAW5i9OwscIyDSTH98zKvNVtKlu7BcWfqx2Ex7Z6Ba8nkevf
Pdvo5rp+0f3sKHdbqCuaCeAhTnT5P6vPC2MhZBnRTkD58QawOl7EiIrhHUoR
-----END RSA PRIVATE KEY-----
"""

FAKE_SERVICE_ACCOUNT_INFO = {
    "type": "service_account",
    "project_id": "fake-project",
    "private_key_id": "fake-key-id",
    "private_key": FAKE_PRIVATE_KEY_PEM,
    "client_email": "fake@fake-project.iam.gserviceaccount.com",
    "client_id": "123456789",
    "token_uri": "https://oauth2.googleapis.com/token",
}


def _b64(info: dict) -> str:
    return base64.b64encode(json.dumps(info).encode("utf-8")).decode("ascii")


def test_decode_service_account_info_requires_env_var(monkeypatch):
    monkeypatch.setattr(
        google_service_account_service.settings, "google_service_account_json_b64", None
    )

    with pytest.raises(google_service_account_service.GoogleServiceAccountConfigurationError):
        google_service_account_service.decode_service_account_info()


def test_decode_service_account_info_rejects_invalid_base64(monkeypatch):
    monkeypatch.setattr(
        google_service_account_service.settings,
        "google_service_account_json_b64",
        "not-valid-base64!!!",
    )

    with pytest.raises(google_service_account_service.GoogleServiceAccountConfigurationError):
        google_service_account_service.decode_service_account_info()


def test_decode_service_account_info_rejects_invalid_json(monkeypatch):
    monkeypatch.setattr(
        google_service_account_service.settings,
        "google_service_account_json_b64",
        base64.b64encode(b"not-json").decode("ascii"),
    )

    with pytest.raises(google_service_account_service.GoogleServiceAccountConfigurationError):
        google_service_account_service.decode_service_account_info()


def test_decode_service_account_info_returns_parsed_dict(monkeypatch):
    monkeypatch.setattr(
        google_service_account_service.settings,
        "google_service_account_json_b64",
        _b64(FAKE_SERVICE_ACCOUNT_INFO),
    )

    info = google_service_account_service.decode_service_account_info()

    assert info == FAKE_SERVICE_ACCOUNT_INFO


def test_get_google_service_account_credentials_builds_credentials(monkeypatch):
    monkeypatch.setattr(
        google_service_account_service.settings,
        "google_service_account_json_b64",
        _b64(FAKE_SERVICE_ACCOUNT_INFO),
    )

    credentials = google_service_account_service.get_google_service_account_credentials(
        ["https://www.googleapis.com/auth/spreadsheets"]
    )

    assert credentials.service_account_email == FAKE_SERVICE_ACCOUNT_INFO["client_email"]
