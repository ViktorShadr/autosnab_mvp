# АвтоСнаб — Backend MVP-2 для команды 2

Backend-проект MVP-2 по сценарию приемки товара заведением.

Фокус MVP-2:

- корректировки через AI Agent / текстовый parser;
- распознавание и учет зачеркнутых строк в накладной;
- частичная приемка;
- обработка лишних товаров;
- подготовка и mock-передача данных в учетную систему / iiko;
- выгрузка MVP-таблиц приемки в CSV-формате для Google Sheets.

## Что реализовано

### Приемка

- `POST /api/v1/receiving/start` — старт приемки.
- `POST /api/v1/receiving/{receiving_id}/documents` — сохранение документа/накладной.
- `POST /api/v1/receiving/{receiving_id}/compare-invoice` — сверка накладной с заявкой.
- `POST /api/v1/receiving/{receiving_id}/corrections` — применение JSON-корректировок.
- `POST /api/v1/receiving/{receiving_id}/corrections/parse` — разбор текстовой корректировки в JSON-команду.
- `POST /api/v1/receiving/{receiving_id}/corrections/text` — разбор и применение текстовой корректировки.
- `POST /api/v1/receiving/{receiving_id}/confirm` — подтверждение полной/частичной приемки.
- `GET /api/v1/receiving/{receiving_id}/accounting-payload` — payload для учетной системы.
- `POST /api/v1/receiving/export/google-sheets-mvp` — CSV-выгрузка листов приемки.

### Учетная система / iiko MVP

- `POST /api/v1/accounting/mappings` — ручная связь товара поставщика с номенклатурой учетной системы.
- `GET /api/v1/accounting/mappings` — список связей.
- `POST /api/v1/accounting/receivings/{receiving_id}/send` — mock-передача приемки в учетную систему.
- `GET /api/v1/accounting/exports` — история подготовленных/отправленных payload.

### Статусы позиций

- `matched` — товар совпал.
- `missing` — товар из заявки не найден в накладной.
- `extra` — товар есть в накладной, но отсутствует в заявке.
- `quantity_mismatch` — отличается количество.
- `price_mismatch` — отличается цена.
- `replacement_candidate` — возможная замена.
- `crossed_out` — строка зачеркнута.
- `accepted` — пользователь подтвердил позицию.
- `rejected` — пользователь отклонил позицию.
- `manual_review` — нужна ручная проверка.

## Запуск локально

```bash
cd autosnab_mvp2
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -r backend/requirements.txt
cd backend
uvicorn app.main:app --reload
```

Swagger:

```text
http://localhost:8000/docs
```

## Запуск через Docker

```bash
cd autosnab_mvp2
docker compose up --build
```

## Тесты

```bash
pytest
```

## CSV-выгрузка для Google Sheets MVP

Endpoint:

```text
POST /api/v1/receiving/export/google-sheets-mvp
```

Создает файлы:

```text
backend/exports/priemka.csv
backend/exports/priemka_pozicii.csv
backend/exports/priemka_dokumenty.csv
```

Эти файлы соответствуют MVP-листам:

- `Приемка`
- `Приемка позиции`
- `Приемка документы`

## Ограничения MVP-2

- OCR/Vision не подключен как реальный внешний сервис: backend принимает уже распознанные данные накладной.
- AI Agent реализован как безопасный deterministic parser текстовых корректировок. Он возвращает JSON-команду, а изменения делает backend после валидации.
- iiko-интеграция выполнена как mock-передача и сохранение export payload. Для реальной отправки нужны доступы к iiko API.
- MAX/Telegram/n8n остаются внешним слоем, который должен вызывать эти backend endpoint'ы.
