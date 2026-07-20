# Задача: интеграция с API СБИС (Saby ЭДО) — v3, ревизия с учётом Diadoc-адаптера

> Ревизия от 2026-07-20. v2 этого файла было проверено против `docs/wiki/sbis-edo-integration.md`
> и против уже смерженного в `over_version` Diadoc-адаптера (см. `docs/wiki/diadoc-integration.md`).
> Главный вывод ревизии: это **не первая ЭДО-интеграция в проекте** — Diadoc (Контур) уже решает
> практически идентичную задачу (poll → dedupe → download → parse XML/fallback → доставка в
> Google Sheets, с ретраями и dead-letter). SBIS должен быть построен как **структурная копия**
> Diadoc-адаптера с другим клиентом протокола, а не спроектирован заново. Ниже — конкретные файлы
> и функции, которые нужно зеркалить, с указанием, где протоколы SBIS и Diadoc расходятся и это
> зеркалирование ломается.

## Статус на входе

Доступ к API СБИС подтверждён пользователем как реальный (production, не sandbox
`fix-online.sbis.ru`). Референс-скрипт `sbis_api_test.py` теперь сохранён в корне
репозитория, а реальный ответ `СБИС.СписокИзменений` (2026-07-13, организация
ИНН `7604094967`) сохранён и зарегистрирован как `src_20260720_sbis_dump` в
`../autosnab_mvp_raw/inbox/sbis_changes_dump_2026-07-13.json`. Технические факты
ниже сверены с этим реальным дампом — расхождения и новые находки отмечены явно.

## Подтверждённые технические факты об API СБИС

(Без изменений от v2 — эта секция описывает протокол SBIS, а не архитектуру проекта,
и подтверждена пользователем как основанная на реальном доступе.)

**Протокол и адреса**
- JSON-RPC поверх HTTPS.
- Аутентификация: `POST https://online.sbis.ru/auth/service/`, метод
  `СБИС.Аутентифицировать`, тело `{"Параметр": {"Логин": ..., "Пароль": ...}}`.
  Возвращает SID в поле `result`.
- Остальные методы: `POST https://online.sbis.ru/service/?srv=1`, SID
  передаётся в заголовке `X-SBISSessionID`.
- **Обязательно** `Content-Type: application/json; charset=utf-8` — без явного
  `charset=utf-8` сервер возвращает ошибку `-32700` (parse error).
- Логина/пароля обычного пользователя СБИС (даже с полными правами админа)
  достаточно для чтения входящих через `СБИС.СписокИзменений`.

**Получение списка изменений**
- Метод `СБИС.СписокИзменений`, параметр `{"Фильтр": {"ДатаВремяС": "<дата>"}}`.
- Формат даты **обязательно** `ДД.ММ.ГГГГ ЧЧ:ММ:СС` — дата без времени возвращает
  ошибку `-32000`.
- Ответ: `result.Документ[]`, `result.Навигация.ЕстьЕще` для пагинации (курсорная
  догрузка по `ДатаВремяС` последнего полученного события).
- **Один и тот же документ встречается в ответе несколько раз** — по одной записи
  на каждое связанное событие. Обязательна дедупликация по `Документ.Идентификатор`.

**Структура документа**
- `Документ.Тип` — фильтровать по этому полю, не по названию: `ДокОтгрВх` (накладные/УПД,
  основной целевой тип), `СчетВх` (входящий счёт, тоже целевой), `АктСверВх`/`ДоговорВх`
  (не нужны).
- `Документ.Событие[].Вложение[]`, `Вложение.Служебный` (`"Да"`/`"Нет"`) — служебные
  вложения (извещения, квитанции) не скачивать как первичный документ.
- `Вложение.Файл.Ссылка` — прямая HTTPS-ссылка, обычный `GET` без доп. авторизации
  (подписанный токен уже в ссылке), живёт ~месяц — скачивать сразу при обнаружении.
- `Вложение.Название` содержит расширение — перебирать все неслужебные вложения,
  выбирать `.xml`, игнорировать `.pdf`, если по документу уже есть XML.
- `Контрагент.СвЮЛ`/`Контрагент.СвФЛ` уже приходят в ответе `СписокИзменений` —
  отдельный запрос карточки контрагента не нужен.

**Уточнения по реальному дампу (2026-07-20, см. `sbis-edo-integration.md` →
"Real production dump analysis" за полным разбором):**
- **`Вложение.Тип` — не то же самое, что `Документ.Тип`.** У вложения свой,
  независимый словарь (`УпдДоп`, `УпдДопПокуп`, `УпдСчфДоп`, `ЭДОСч`,
  `ИзвПолуч`, `ПодтвДатОтпр`/`ПодтвДатПол`, пусто). Классификация документа —
  только по `Документ.Тип`; выбор вложения — по `Служебный`+расширению имени,
  **не** по `Вложение.Тип`.
- **`Вложение.Файл.Ссылка` иногда пустая строка** даже у неслужебного вложения
  с заполненным именем файла (подтверждено на двух реальных УПД в дампе) —
  скачивание должно обрабатывать пустую ссылку как «пока недоступна»
  (лог + ретрай/пропуск), а не падать или считать документ битым навсегда.
- **УПД и Счёт используют разные версии XML-схемы** (`ВерсияФормата` УПД —
  `5.01`/`5.03`, Счёт — `1.03`/`TENSOR_1`, видимо другая корневая структура) —
  переиспользование общего `fns_upd_xml_parser_service` для `СчетВх` нужно
  отдельно проверить на реальном XML счёта, не считать рабочим по умолчанию.
- **У одного документа бывает несколько неслужебных вложений сверх целевого**
  (в дампе: счёт-PDF + целевой УПД-XML + ещё три PDF — комплект, ведомость,
  акт покупателя). Правило «XML важнее PDF» решает этот случай корректно, но
  если у документа вообще нет XML и несколько неслужебных PDF — наивный выбор
  «первый попавшийся PDF» может взять не тот файл; нужна вторичная эвристика
  (сверка `Номер`/`Сумма` вложения с `Документ.Номер`/`Сумма`, или разбор
  префикса имени файла).

## Архитектурное решение: зеркалить Diadoc-адаптер

Проект уже прошёл этот путь один раз для Контура. Структура ниже — прямое отображение
существующих файлов `backend/app/{models,services,routers,schemas}/diadoc*` на новые
`*sbis*` файлы. Отличия протокола SBIS от Diadoc сведены в таблицу и учтены точечно —
остальное (дедуп, ретраи, доставка, статусная модель, lease) копируется структурно.

| Diadoc (существует) | SBIS (создать по аналогии) | Что меняется |
|---|---|---|
| `app/models/diadoc.py` (`DiadocSyncState`, `DiadocDocument`, `DiadocArtifact`, `DiadocDelivery`, `DiadocLease`) | `app/models/sbis.py` (`SbisSyncState`, `SbisDocument`, `SbisArtifact`, `SbisDelivery`, `SbisLease`) | `DiadocSyncState.box_id`/`after_index_key` → `SbisSyncState` хранит курсор `last_datetime_from` (значение `ДатаВремяС` последнего обработанного события) вместо `box_id` + `IndexKey`, т.к. у SBIS нет понятия "ящик". `DiadocDocument.message_id/entity_id` → `SbisDocument.sbis_document_id` (значение `Документ.Идентификатор`) как единственный ключ дедупа вместо составного `message_id+entity_id` |
| `app/services/diadoc_client.py` (`DiadocClient`, OAuth-based) | `app/services/sbis_client.py` (`SbisClient`) | Аутентификация проще: не OIDC, а `СБИС.Аутентифицировать` → SID, кэшировать SID в памяти процесса (не в БД), реаутентифицироваться при `-1`/`403`-подобной ошибке истёкшей сессии. Нет отдельного OAuth-роутера/колбэка — не нужен `sbis_oauth_service.py`, только логин/пароль из `.env` |
| `app/services/diadoc_xml_parser_service.py` (`parse_diadoc_invoice_xml`) | **не дублировать** — обобщить | См. ниже "Общий XML-парсер" |
| `app/services/diadoc_sync_service.py` (`sync_diadoc_documents`, `_process_event`, `_process_document`, `_transfer_to_verification`, `_ensure_delivery`, `_execute_delivery`, retry/lease-хелперы) | `app/services/sbis_sync_service.py` (`sync_sbis_documents`, аналогичные приватные функции) | Событийная модель проще: SBIS отдаёт уже сгруппированный по документу список с вложениями за один вызов `СписокИзменений`, тогда как Diadoc требует отдельного `GetMessage`+`GetEntityContent` на вложение. Цикл `_process_event`/`_process_document` можно слить в один проход по `result.Документ[]` |
| `app/services/diadoc_scheduler_service.py` | `app/services/sbis_scheduler_service.py` | Структура 1:1 (daemon-поток, `start_/stop_/status_` тройка, `_scheduler_configuration_ready`) |
| `app/routers/diadoc.py` (`require_diadoc_admin` по `X-Diadoc-Api-Key`, `/status`, `/sync`, `/retry`, `/dead-letter*`, `/oauth/*`) | `app/routers/sbis.py` | Те же эндпоинты кроме `/oauth/*` (не нужен — логин/пароль, не OIDC). Admin-гейт `X-Sbis-Api-Key` с тем же fallback на `settings.bot_api_shared_secret` |
| `app/schemas/diadoc.py` | `app/schemas/sbis.py` | Аналогичные `SbisStatusResponse`/`SbisSyncResponse` |
| `scripts/migrate_diadoc_reliability.py` | `scripts/migrate_sbis_reliability.py` (если ORM-миграции в проекте ручные, как у Diadoc) | Та же схема: создать новые таблицы, ничего не менять в существующих |
| `config.py` `diadoc_*` (26 полей) | `config.py` `sbis_*` | См. список ниже |
| `main.py`: `include_router(diadoc.router, ...)`, `start_diadoc_scheduler()`/`stop_diadoc_scheduler()` в lifespan | то же для `sbis` | 1:1 |
| `tests/test_diadoc_client_reliability.py`, `test_diadoc_sync_service.py`, `test_diadoc_xml_parser_service.py`, `test_diadoc_router_reliability.py`, `test_diadoc_preflight.py`, `test_diadoc_automatic_pipeline.py` | `tests/test_sbis_client_reliability.py`, `test_sbis_sync_service.py`, `test_sbis_router_reliability.py`, `test_sbis_preflight.py`, `test_sbis_automatic_pipeline.py` | Структура тестов та же (моки HTTP, никаких реальных вызовов к SBIS) |

### Общий XML-парсер вместо нового

`diadoc_xml_parser_service.parse_diadoc_invoice_xml` — это уже generic-парсер УПД/счёт-фактуры
в формате **ФНС** (теги `СвСчФакт`, `СвПрод`, `ТаблСчФакт`, `СведТов` и т.д. — это госстандарт
формата, а не что-то специфичное для Диадока). Diadoc-специфичного там всего три места:
`document_form="УПД/ЭДО Диадок"`, `parser_metadata["provider"/"source_channel"] = "diadoc"`,
и префикс `request_id=f"DIADOC-{file_id}"`.

**Вместо нового XML-парсера для SBIS:**
1. Переименовать/обобщить файл в `app/services/fns_upd_xml_parser_service.py`,
   функцию — в `parse_fns_invoice_xml(content, *, file_id, file_url=None, provider="diadoc")`,
   параметризовав те три места по `provider`.
2. `diadoc_xml_parser_service.py` оставить тонкой обёрткой (`parse_diadoc_invoice_xml = partial(parse_fns_invoice_xml, provider="diadoc")`) — не ломать существующие импорты и тесты.
3. `sbis_sync_service.py` вызывает `parse_fns_invoice_xml(content, file_id=..., provider="sbis")`.
4. Если при реальном тестировании обнаружится, что SBIS присылает XML с иной структурой/версией
   ФНС-схемы (`СвДокОбор` вместо `СвСчФакт` и т.п.) — расширять список альтернативных тегов
   в общей функции, не создавать параллельную реализацию.

Единственный риск этого подхода: нужно реально скачать и сверить один настоящий XML-файл от
SBIS, прежде чем полагаться на переиспользование — теги ФНС стабильны по стандарту, но версии
схемы (УПД v1 vs v2) могут отличаться в деталях.

### PDF-fallback: переиспользовать существующий пайплайн, не строить новый

`diadoc_sync_service._parse_unstructured_document` — уже готовый пример правильного паттерна:

```python
def _parse_unstructured_document(path: Path) -> InvoiceReviewCreateRequest:
    extraction = extract_invoice_document(
        str(path), path.name,
        extraction_method=settings.diadoc_unstructured_extraction_method,
    )
    ...
```

Это вызывает уже существующий `document_extraction_service.extract_invoice_document(...)`,
который внутри себя делает OCR/MinerU/OpenAI structured-output + детерминированную нормализацию
и уже умеет выставлять `needs_review`/`Требует проверки` при расхождениях (сумма строк vs
итог, НДС и т.д.) — см. `invoice_normalization_service.py`.

**`sbis_sync_service.py` должен вызывать ту же функцию тем же способом** (`extraction_method=settings.sbis_unstructured_extraction_method`, по умолчанию `"openai"`), когда у документа СБИС нет ни одного `.xml`-вложения, только `.pdf`. Отдельный путь через `opendataloader-pdf` + собственный LLM-вызов (как предлагала v2 этого файла) **не нужен** — это дублирование уже работающей и протестированной бизнес-логики, включая её статусную модель. Своя параллельная статусная модель (`ready_for_review`/`needs_manual_check`/`manual_entry_required`) тоже не нужна — использовать существующие статусы (`needs_review`, флаги `_flag(..., "error")` из `invoice_normalization_service.py`).

### Передача документа в общий core

Как и Diadoc, `sbis_sync_service.py` должен вызывать уже существующие
`invoice_review_service.create_invoice_review(db, payload)` /
`update_invoice_review(db, receiving_id, payload)` /
`create_real_google_sheet_for_review(db, receiving, settings.public_api_base_url)` —
не писать собственную запись в `Receiving`/`ReceivingDocument`/`ReceivingItem` напрямую и не
писать собственный Google Sheets writer. `_transfer_to_verification` в `diadoc_sync_service.py`
— готовый образец: искать существующую карточку по документу/сообщению, иначе по
номеру основания (`_find_order_receiving`), иначе создавать новую.

## Список новых настроек (`config.py`)

Мирroring `diadoc_*` naming один в один, под SBIS:

```
sbis_integration_enabled: bool = False
sbis_api_base_url: str = "https://online.sbis.ru"
sbis_auth_url: str = "https://online.sbis.ru/auth/service/"
sbis_login: str | None = None
sbis_password: str | None = None
sbis_timeout_seconds: float = 30.0
sbis_sync_limit: int = 100
sbis_documents_dir: str = "uploads/sbis"
sbis_scheduler_enabled: bool = True
sbis_sync_interval_seconds: int = 300  # 5-15 минут по ТЗ; 300с — как у Diadoc
sbis_retry_max_attempts: int = 5
sbis_retry_base_delay_seconds: int = 60
sbis_retry_batch_size: int = 50
sbis_delivery_stale_seconds: int = 600
sbis_sync_lease_seconds: int = 1800
sbis_max_pages_per_sync: int = 10
sbis_document_types: str = "ДокОтгрВх,СчетВх"  # настраиваемое множество из ТЗ
sbis_max_attachment_bytes: int = 100_000_000
sbis_admin_api_key: str | None = None
sbis_parse_unstructured_attachments: bool = True
sbis_unstructured_extraction_method: str = "openai"
```

Секреты (`sbis_login`, `sbis_password`) — только через `.env`/`.env.example`, без хардкода,
как у всех остальных интеграций проекта.

## Явно вне рамок этой задачи

(Без изменений от v2.)
- Отправка извещений о получении (ИОП) и подписание документов через
  API/сертификат/ЭЦП — сервис только читает входящие.
- Интеграция с учётной системой (iiko) — отдельная задача.
- Собственный PDF-fallback движок (`opendataloader-pdf` + отдельный LLM-вызов) —
  переиспользуется существующий `document_extraction_service.py`.
- Собственный XML-парсер УПД — переиспользуется/обобщается `diadoc_xml_parser_service.py`.
- OAuth/OIDC-флоу — SBIS использует логин/пароль + SID, отдельный `sbis_oauth_service.py` не нужен.

## Как действовать

1. Принести/сверить `sbis_api_test.py` (или сохранённые реальные ответы `СписокИзменений`)
   перед тем, как полагаться на технические факты выше.
2. Обобщить `diadoc_xml_parser_service.py` → `fns_upd_xml_parser_service.py` первым шагом —
   это малый, изолированный рефакторинг, который не трогает поведение Diadoc (тесты
   `test_diadoc_xml_parser_service.py` должны продолжать проходить без изменений).
3. `sbis_client.py`: аутентификация (СБИС.Аутентифицировать + кэш SID + реаутентификация),
   `get_changes` с пагинацией по `ЕстьЕще`, скачивание вложения по прямой ссылке.
4. `models/sbis.py` + миграция (по образцу `migrate_diadoc_reliability.py`, если миграции в
   проекте ручные, а не Alembic).
5. `sbis_sync_service.py`: дедуп по `Документ.Идентификатор`, фильтр по `Документ.Тип`,
   выбор `.xml` > `.pdf` среди неслужебных вложений, вызов общего XML-парсера или
   `extract_invoice_document(...)` для PDF-fallback, передача в
   `create_invoice_review`/`update_invoice_review`/`create_real_google_sheet_for_review`,
   ретраи и dead-letter по образцу `_execute_delivery`/`_record_failure`.
6. `sbis_scheduler_service.py` + `routers/sbis.py` + `schemas/sbis.py` — по образцу Diadoc.
7. Wiring в `main.py` (роутер + старт/стоп scheduler в lifespan).
8. Тесты по каждому шагу, моки HTTP, без обращения к реальному SBIS API.
9. Смоук-тест на одном реальном документе СБИС (раз доступ подтверждён реальный) — сверить,
   что дедуп не плодит второй `Receiving` при повторном запуске синка.
