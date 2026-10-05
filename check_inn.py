"""
Проверка статуса организаций по ИНН через DaData.

Читает ИНН из входного файла (по одному в строке) и раскладывает их в два файла:
действующие (статус ACTIVE) и недействующие (все остальные статусы + не найденные).

Запуск:
    python check_inn.py                    # inn.txt -> active.txt / inactive.txt
    python check_inn.py my_inns.txt        # свой входной файл
    DADATA_MOCK=1 python check_inn.py      # без запросов, через mock_dadata.py
"""

import os
import re
import sys
import time

import requests

MOCK = os.environ.get("DADATA_MOCK") == "1"
if MOCK:
    import mock_dadata
    mock_dadata.install()

TOKEN = os.environ.get("DADATA_TOKEN")
URL = "https://suggestions.dadata.ru/suggestions/api/4_1/rs/findById/party"

INPUT_FILE = sys.argv[1] if len(sys.argv) > 1 else "inn.txt"
# в режиме мока пишем в отдельные файлы, чтобы не затереть настоящие результаты
ACTIVE_FILE = "active_mock.txt" if MOCK else "active.txt"
INACTIVE_FILE = "inactive_mock.txt" if MOCK else "inactive.txt"
RETRY_DELAY = 0 if MOCK else 2
REQUEST_DELAY = 0 if MOCK else 0.05

STATUS_RU = {
    "ACTIVE": "действующая",
    "LIQUIDATING": "ликвидируется",
    "LIQUIDATED": "ликвидирована",
    "BANKRUPT": "банкротство",
    "REORGANIZING": "в процессе реорганизации",
}


def find_party(inn: str, token: str | None = TOKEN) -> dict | None:
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "Authorization": f"Token {token}",
    }
    payload = {"query": inn, "branch_type": "MAIN"}
    for attempt in range(3):
        try:
            resp = requests.post(URL, json=payload, headers=headers, timeout=15)
            if resp.status_code == 429 and attempt < 2:  # превышен лимит запросов
                time.sleep(RETRY_DELAY)
                continue
            resp.raise_for_status()
            suggestions = resp.json().get("suggestions", [])
            return suggestions[0] if suggestions else None
        except requests.ConnectionError:
            if attempt < 2:
                time.sleep(RETRY_DELAY)
                continue
            raise


def read_inns(path: str) -> list[str]:
    with open(path, encoding="utf-8") as f:
        inns = [re.sub(r"\D", "", line) for line in f]
    # убираем пустые строки и дубли, сохраняя порядок
    return list(dict.fromkeys(i for i in inns if i))


def check(inn: str, token: str | None = TOKEN) -> tuple[str, str]:
    """Проверить один ИНН. Возвращает (наименование или комментарий, статус по-русски)."""
    if len(inn) not in (10, 12):
        return "-", "некорректный ИНН"
    try:
        party = find_party(inn, token)
    except Exception as e:
        return str(e), "ошибка запроса"
    if party is None:
        return "-", "не найдена"
    status = party["data"].get("state", {}).get("status", "")
    return party["value"], STATUS_RU.get(status, status)


def main():
    inns = read_inns(INPUT_FILE)
    print(f"ИНН к проверке: {len(inns)}")

    with open(ACTIVE_FILE, "w", encoding="utf-8") as active, \
         open(INACTIVE_FILE, "w", encoding="utf-8") as inactive:
        for n, inn in enumerate(inns, 1):
            name, status = check(inn)
            if status == "ошибка запроса":
                line = f"{inn}\t-\tошибка запроса: {name}"
            else:
                line = f"{inn}\t{name}\t{status}"
            (active if status == STATUS_RU["ACTIVE"] else inactive).write(line + "\n")
            print(f"[{n}/{len(inns)}] {line}")
            time.sleep(REQUEST_DELAY)  # лимит DaData — до 30 запросов в секунду

    print(f"\nГотово: {ACTIVE_FILE}, {INACTIVE_FILE}")


if __name__ == "__main__":
    main()
