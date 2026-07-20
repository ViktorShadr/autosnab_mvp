"""
Тестовый скрипт проверки доступа к API СБИС (Saby EDO).

Что делает:
1. Аутентифицируется по логину/паролю -> получает SID (идентификатор сессии).
2. Запрашивает СБИС.СписокИзменений за последние N дней -> список событий
   по входящим документам (если доступ к API есть, вернётся список; если
   нет — увидим код ошибки и текст, что именно не разрешено).

Требования: pip install requests
"""

import json
import requests
from datetime import datetime, timedelta

# ==== НАСТРОЙКИ — заполните перед запуском ====
LOGIN = "login"
PASSWORD = "pass"
ACCOUNT_NUMBER = None  # укажите строкой, если у вас несколько кабинетов/организаций на аккаунте
DAYS_BACK = 7  # за сколько дней назад смотреть изменения

AUTH_URL = "https://online.sbis.ru/auth/service/"
API_URL = "https://online.sbis.ru/service/?srv=1"

HEADERS = {
    "Content-Type": "application/json; charset=utf-8",
    "Accept": "application/json",
}


def rpc_call(url, method, params, sid=None):
    """Универсальный вызов JSON-RPC метода СБИС."""
    payload = {
        "jsonrpc": "2.0",
        "method": method,
        "params": params,
        "id": 1,
    }
    headers = dict(HEADERS)
    if sid:
        headers["X-SBISSessionID"] = sid

    resp = requests.post(url, headers=headers, data=json.dumps(payload, ensure_ascii=False).encode("utf-8"))
    print(f"--- {method} ---")
    print("HTTP статус:", resp.status_code)
    try:
        data = resp.json()
    except ValueError:
        print("Не удалось распарсить JSON. Тело ответа:")
        print(resp.text[:2000])
        return None

    print(json.dumps(data, ensure_ascii=False, indent=2)[:3000])
    return data


def authenticate():
    params = {
        "Параметр": {
            "Логин": LOGIN,
            "Пароль": PASSWORD,
        }
    }
    if ACCOUNT_NUMBER:
        params["Параметр"]["НомерАккаунта"] = ACCOUNT_NUMBER

    data = rpc_call(AUTH_URL, "СБИС.Аутентифицировать", params)
    if not data:
        return None

    if "error" in data and data["error"]:
        print("\n❌ ОШИБКА АУТЕНТИФИКАЦИИ:", data["error"])
        return None

    sid = data.get("result")
    if not sid:
        print("\n❌ SID не получен, проверьте ответ выше.")
        return None

    print("\n✅ Аутентификация успешна. SID получен.")
    return sid


import os

# Ключевые слова в "Регламент.Название" / "Название" документа, по которым
# отбираем накладные / УПД / счета-фактуры. Дополните под свои формулировки,
# когда увидите реальные названия регламентов в выгрузке.
DOC_TYPE_KEYWORDS = [
    "накладная",
    "упд",
    "счет-фактура",
    "счёт-фактура",
    "торг-12",
    "акт",
]

DOWNLOAD_DIR = "downloaded_docs"
FULL_DUMP_FILE = "last_changes_full.json"


def is_target_document(doc):
    """Проверяем, похож ли документ на накладную/УПД/счет-фактуру по названию/регламенту."""
    haystack = " ".join([
        doc.get("Название", ""),
        (doc.get("Регламент") or {}).get("Название", ""),
        (doc.get("Регламент") or {}).get("Идентификатор", ""),
    ]).lower()
    return any(kw in haystack for kw in DOC_TYPE_KEYWORDS)


def iter_attachments(doc):
    """Проходит по всем событиям документа и отдаёт вложения по одному."""
    for event in doc.get("Событие", []) or []:
        for attach in event.get("Вложение", []) or []:
            yield attach


def get_attachment_url(attach):
    """
    Пытается достать ссылку на файл из разных возможных мест структуры вложения.
    Структура API может отличаться в зависимости от типа документа/регламента,
    поэтому проверяем несколько вариантов.
    """
    # Вариант 1: Вложение.Файл.Ссылка
    file_obj = attach.get("Файл")
    if isinstance(file_obj, dict) and file_obj.get("Ссылка"):
        return file_obj["Ссылка"]

    # Вариант 2: Ссылка прямо в объекте вложения
    if attach.get("Ссылка"):
        return attach["Ссылка"]

    return None


def download_attachment(url, filename, sid):
    """Скачивает файл вложения по ссылке, используя ту же сессию (SID)."""
    headers = {
        "X-SBISSessionID": sid,
        "Cookie": f"sid={sid}",
    }
    resp = requests.get(url, headers=headers)
    if resp.status_code != 200:
        print(f"   ❌ Не удалось скачать {filename}: HTTP {resp.status_code}")
        return False

    os.makedirs(DOWNLOAD_DIR, exist_ok=True)
    path = os.path.join(DOWNLOAD_DIR, filename)
    with open(path, "wb") as f:
        f.write(resp.content)
    print(f"   ✅ Сохранено: {path}")
    return True


def get_changes(sid):
    date_from = (datetime.now() - timedelta(days=DAYS_BACK)).strftime("%d.%m.%Y %H:%M:%S")
    params = {
        "Фильтр": {
            "ДатаВремяС": date_from,
        }
    }
    data = rpc_call(API_URL, "СБИС.СписокИзменений", params, sid=sid)
    if not data:
        return

    if "error" in data and data["error"]:
        print("\n❌ ОШИБКА ДОСТУПА К API ДОКУМЕНТООБОРОТА:", data["error"])
        print("   -> Скорее всего нужно включить опцию API ЭДО в тарифе, либо нет прав на этот раздел.")
        return

    result = data.get("result")
    if result is None:
        print("\n⚠️ Пустой результат — либо нет событий за период, либо нет доступа.")
        return

    # Сохраняем полный ответ целиком в файл — вывод в консоли обрезается,
    # а нам нужно увидеть реальную структуру вложений (в т.ч. поле со ссылкой).
    with open(FULL_DUMP_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"\n📄 Полный ответ сохранён в {FULL_DUMP_FILE} — посмотрите там структуру вложений.")

    documents = (result or {}).get("Документ", []) or []
    print(f"\nВсего документов в выгрузке: {len(documents)}")

    target_docs = [d for d in documents if is_target_document(d)]
    print(f"Из них похожих на накладную/УПД/счет-фактуру (по ключевым словам): {len(target_docs)}")

    if not target_docs:
        print("\n⚠️ Ни один документ не подошёл под фильтр DOC_TYPE_KEYWORDS.")
        print("   Откройте", FULL_DUMP_FILE, ", посмотрите реальные значения")
        print("   'Название' / 'Регламент.Название' и дополните список ключевых слов в скрипте.")
        return

    for doc in target_docs:
        print(f"\n--- Документ: {doc.get('Название')} (№{doc.get('Номер')} от {doc.get('Дата')}) ---")
        found_any = False
        for attach in iter_attachments(doc):
            found_any = True
            name = attach.get("Название", "без_имени")
            url = get_attachment_url(attach)
            ext = os.path.splitext(name)[1].lower()
            marker = "⭐ XML" if ext == ".xml" else ext.upper() or "?"
            print(f"  Вложение: {name} [{marker}]")
            if not url:
                print("   ⚠️ Ссылка на файл не найдена в структуре вложения — проверьте",
                      FULL_DUMP_FILE, "вручную.")
                continue
            download_attachment(url, name, sid)
        if not found_any:
            print("  (вложений не найдено в этом документе)")


if __name__ == "__main__":
    sid = authenticate()
    if sid:
        get_changes(sid)
    else:
        print("\nОстановлено: без успешной аутентификации дальнейшие вызовы невозможны.")
