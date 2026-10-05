"""
Мок DaData findById/party — для проверки check_inn.py без реальных запросов.

Подменяет requests.post: ответ детерминированно зависит от ИНН (один и тот же ИНН
всегда даёт один и тот же результат), так что прогоны воспроизводимы.

Распределение по crc32(ИНН) % 100:
    0–69   ACTIVE
    70–77  LIQUIDATED
    78–81  LIQUIDATING
    82–84  BANKRUPT
    85–86  REORGANIZING
    87–92  не найдена (пустой suggestions)
    93–96  первый запрос 429, потом ACTIVE        — проверка ретрая
    97     всегда 429                               — ретраи исчерпаны -> HTTPError
    98     первый запрос ConnectionError, потом ACTIVE
    99     всегда ConnectionError

Можно задать ответ для конкретного ИНН явно через OVERRIDES.
"""

import zlib
from collections import defaultdict

import requests

STATUSES = [
    (70, "ACTIVE"),
    (78, "LIQUIDATED"),
    (82, "LIQUIDATING"),
    (85, "BANKRUPT"),
    (87, "REORGANIZING"),
    (93, None),  # не найдена
]

# Явные ответы для конкретных ИНН: статус или None (не найдена)
OVERRIDES: dict[str, str | None] = {
    "7812014560": "ACTIVE",
}

_attempts: defaultdict[str, int] = defaultdict(int)


class FakeResponse:
    def __init__(self, status_code: int, data: dict | None = None):
        self.status_code = status_code
        self._data = data or {}

    def json(self) -> dict:
        return self._data

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"{self.status_code} Mock Error", response=self)


def _party(inn: str, status: str) -> dict:
    return {
        "value": f'ООО "ТЕСТ-{inn[-4:]}"',
        "data": {"inn": inn, "state": {"status": status}},
    }


def _found(inn: str, status: str | None) -> FakeResponse:
    suggestions = [_party(inn, status)] if status else []
    return FakeResponse(200, {"suggestions": suggestions})


def fake_post(url, json=None, headers=None, timeout=None, **kwargs) -> FakeResponse:
    inn = str((json or {}).get("query", ""))
    _attempts[inn] += 1
    attempt = _attempts[inn]

    if inn in OVERRIDES:
        return _found(inn, OVERRIDES[inn])

    bucket = zlib.crc32(inn.encode()) % 100

    if bucket == 97:
        return FakeResponse(429)
    if bucket == 99:
        raise requests.ConnectionError("Mock connection error")
    if 93 <= bucket <= 96:
        return FakeResponse(429) if attempt == 1 else _found(inn, "ACTIVE")
    if bucket == 98:
        if attempt == 1:
            raise requests.ConnectionError("Mock connection error")
        return _found(inn, "ACTIVE")

    for upper, status in STATUSES:
        if bucket < upper:
            return _found(inn, status)
    raise AssertionError("unreachable")


def install():
    """Подменить requests.post на мок."""
    requests.post = fake_post
