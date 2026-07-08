# Telegram Bot Node-By-Node Setup

This is the exact UI-oriented setup guide for the current
`telegram-bot-mvp.workflow.json`.

Use it when you want to fill every visible block in `n8n` manually and keep it
aligned with the repo workflow.

## Before node setup

### 1. Create the Data Table

Create a Data Table named `telegram_bot_sessions`.

Recommended columns:

- `chat_id` - text
- `user_id` - text
- `username` - text
- `status` - text
- `files_json` - text
- `organization_name` - text
- `point_name` - text
- `backend_upload_id` - text
- `backend_trace_id` - text

### 2. Prepare environment variables

Use the values from:

- `n8n/telegram-bot-mvp.env.example`

Minimum required:

- `BACKEND_BASE_URL`
- `BOT_SOURCE_CHANNEL`
- `BOT_DOCUMENT_KIND`
- `BACKEND_CREATE_GOOGLE_SHEET`
- `BACKEND_EXTRACTION_METHOD`
- `DEFAULT_ORGANIZATION_NAME`
- `DEFAULT_POINT_NAME`

### 3. Telegram credentials

Create one Telegram credential in `n8n` and attach it to all Telegram nodes.

## Node setup

## 1. `Telegram Trigger`

Type:

- `Telegram Trigger`

Fill:

- `Updates` -> `message`

Credentials:

- choose your Telegram bot credential

## 2. `Normalize Update`

Type:

- `Code`

Paste into `JavaScript Code`:

```javascript
const msg = $json.message || {};
const text = String(msg.text || '').trim();
const chatId = msg.chat?.id ? String(msg.chat.id) : null;
const userId = msg.from?.id ? String(msg.from.id) : null;
const username = msg.from?.username || [msg.from?.first_name, msg.from?.last_name].filter(Boolean).join(' ') || null;
const photo = Array.isArray(msg.photo) && msg.photo.length ? msg.photo[msg.photo.length - 1] : null;
const document = msg.document || null;
const fileId = document?.file_id || photo?.file_id || null;
const fileName = document?.file_name || (photo ? `telegram-photo-${photo.file_unique_id || Date.now()}.jpg` : null);
let intent = 'unknown';
if (text === '/start' || text === 'Новый документ') intent = 'start_session';
else if (text === 'Готово') intent = 'finalize';
else if (text === 'Статус') intent = 'status';
else if (text === 'Сбросить') intent = 'reset';
else if (fileId) intent = 'append_file';
return [{ json: { intent, text, chatId, userId, username, fileId, fileName, raw: $json } }];
```

## 3. `Route Intent`

Type:

- `Switch`

Mode:

- `Rules`

Add 6 rules in this exact order:

1. `={{$json.intent}}` equals `start_session`
2. `={{$json.intent}}` equals `append_file`
3. `={{$json.intent}}` equals `finalize`
4. `={{$json.intent}}` equals `status`
5. `={{$json.intent}}` equals `reset`
6. `={{$json.intent}}` equals `unknown`

Important:

- keep `Case Sensitive = true`
- keep strict type validation

## 4. `Start Session Store`

Type:

- `Data Table`

Fill:

- `Resource` -> `Row`
- `Operation` -> `Upsert`
- `Data table` -> `telegram_bot_sessions`
- `Matching Columns` -> `chat_id`
- `Mapping Column Mode` -> `Map Each Column Manually`

Column values:

- `chat_id` -> `={{$json.chatId}}`
- `user_id` -> `={{$json.userId}}`
- `username` -> `={{$json.username}}`
- `status` -> `collecting`
- `files_json` -> `=[]`
- `organization_name` -> `={{$env.DEFAULT_ORGANIZATION_NAME || ''}}`
- `point_name` -> `={{$env.DEFAULT_POINT_NAME || ''}}`
- `backend_upload_id` -> `=`
- `backend_trace_id` -> `=`

## 5. `Reply Session Opened`

Type:

- `Telegram`

Operation:

- `Send Message`

Fill:

- `Chat ID` -> `={{$json.chatId}}`
- `Text` -> `Новая сессия открыта. Отправьте страницы одного документа, затем нажмите «Готово».`

## 6. `Load Session For File`

Type:

- `Data Table`

Fill:

- `Resource` -> `Row`
- `Operation` -> `Get`
- `Data table` -> `telegram_bot_sessions`

Filter:

- `chat_id` `eq` `={{$json.chatId}}`

## 7. `Append File To Session`

Type:

- `Code`

Paste:

```javascript
const session = $json.data?.[0] || {};
if (!session.id) {
  return [{ json: { ...$json, appendError: 'Сначала откройте сессию командой Новый документ.' } }];
}
const files = JSON.parse(session.files_json || '[]');
files.push({ fileId: $json.fileId, fileName: $json.fileName, addedAt: new Date().toISOString() });
return [{ json: { ...$json, sessionRowId: session.id, filesJson: JSON.stringify(files), filesCount: files.length } }];
```

## 8. `Check Append Error`

Type:

- `If`

Condition:

- `={{$json.appendError || ''}}`
- operator -> `is not empty`

Routing:

- `true` -> `Reply Append Error`
- `false` -> `Store Appended File`

## 9. `Reply Append Error`

Type:

- `Telegram`

Fill:

- `Chat ID` -> `={{$json.chatId}}`
- `Text` -> `={{$json.appendError}}`

## 10. `Store Appended File`

Type:

- `Data Table`

Fill:

- `Resource` -> `Row`
- `Operation` -> `Update`
- `Data table` -> `telegram_bot_sessions`
- `Row ID` -> `={{$json.sessionRowId}}`
- `Mapping Column Mode` -> `Map Each Column Manually`

Column values:

- `files_json` -> `={{$json.filesJson}}`
- `status` -> `collecting`

## 11. `Reply File Added`

Type:

- `Telegram`

Fill:

- `Chat ID` -> `={{$json.chatId}}`
- `Text` -> `Файл добавлен в текущую сессию. Когда все страницы отправлены, нажмите «Готово».`

## 12. `Load Session Finalize`

Type:

- `Data Table`

Fill:

- `Resource` -> `Row`
- `Operation` -> `Get`
- `Data table` -> `telegram_bot_sessions`

Filter:

- `chat_id` `eq` `={{$json.chatId}}`

## 13. `Prepare Finalize`

Type:

- `Code`

Paste:

```javascript
const session = $json.data?.[0] || {};
const files = JSON.parse(session.files_json || '[]');
if (!session.id) {
  return [{ json: { ...$json, finalizeError: 'Сначала откройте сессию командой Новый документ.' } }];
}
if (!files.length) {
  return [{ json: { ...$json, finalizeError: 'В текущей сессии нет файлов.' } }];
}
const uploadContract = {
  source_channel: $env.BOT_SOURCE_CHANNEL || 'telegram_bot',
  document_kind: $env.BOT_DOCUMENT_KIND || 'primary_document',
  source_user_id: $json.userId || session.user_id,
  source_username: $json.username || session.username || null,
  source_chat_id: $json.chatId || session.chat_id,
  organization_name: session.organization_name || $env.DEFAULT_ORGANIZATION_NAME || null,
  point_name: session.point_name || $env.DEFAULT_POINT_NAME || null,
  create_google_sheet: String($env.BACKEND_CREATE_GOOGLE_SHEET || 'false'),
  extraction_method: $env.BACKEND_EXTRACTION_METHOD || 'openai'
};
return [{ json: { ...$json, sessionRowId: session.id, session, files, filesCount: files.length, uploadContract } }];
```

## 14. `Check Finalize Error`

Type:

- `If`

Condition:

- `={{$json.finalizeError || ''}}`
- operator -> `is not empty`

Routing:

- `true` -> `Reply Finalize Error`
- `false` -> `Upload To Backend Contract`

## 15. `Reply Finalize Error`

Type:

- `Telegram`

Fill:

- `Chat ID` -> `={{$json.chatId}}`
- `Text` -> `={{$json.finalizeError}}`

## 16. `Upload To Backend Contract`

Type:

- `HTTP Request`

Fill:

- `Method` -> `POST`
- `URL` -> `={{$env.BACKEND_BASE_URL + '/api/v1/invoice-review/bot/upload-document-live'}}`
- `Send Headers` -> enabled
- header `Accept` -> `application/json`
- `Send Body` -> enabled
- `Content Type` -> `Multipart Form-Data`

Body parameters:

- `source_channel` -> `={{$json.uploadContract.source_channel}}`
- `document_kind` -> `={{$json.uploadContract.document_kind}}`
- `source_user_id` -> `={{$json.uploadContract.source_user_id}}`
- `source_username` -> `={{$json.uploadContract.source_username}}`
- `source_chat_id` -> `={{$json.uploadContract.source_chat_id}}`
- `organization_name` -> `={{$json.uploadContract.organization_name}}`
- `point_name` -> `={{$json.uploadContract.point_name}}`
- `create_google_sheet` -> `={{$json.uploadContract.create_google_sheet}}`
- `extraction_method` -> `={{$json.uploadContract.extraction_method}}`

Important:

- this node still needs real repeated `files[]` binary parts
- the current repo workflow freezes metadata only
- Telegram `getFile` + binary download + multipart file binding is still a manual assembly step in the live `n8n` instance

## 17. `Map Upload Outcome`

Type:

- `Code`

Paste:

```javascript
const source = $json;
const status = source.status;
let replyText = 'Документ принят в обработку.';
if (status === 'unsupported_format') {
  replyText = source.message || 'Файл получен, но этот формат пока не поддерживается.';
} else if (status === 'accepted_for_processing') {
  replyText = `Документ принят в обработку. ID загрузки: ${source.upload_id}`;
}
return [{ json: { ...source, replyText } }];
```

## 18. `Store Backend IDs`

Type:

- `Data Table`

Fill:

- `Resource` -> `Row`
- `Operation` -> `Update`
- `Data table` -> `telegram_bot_sessions`
- `Row ID` -> `={{$item(0).$node['Prepare Finalize'].json.sessionRowId}}`

Column values:

- `status` -> `={{$json.status}}`
- `backend_upload_id` -> `={{$json.upload_id || ''}}`
- `backend_trace_id` -> `={{$json.trace_id || ''}}`

## 19. `Reply Uploaded`

Type:

- `Telegram`

Fill:

- `Chat ID` -> `={{$item(0).$node['Normalize Update'].json.chatId}}`
- `Text` -> `={{$json.replyText}}`

## 20. `Load Session Status`

Type:

- `Data Table`

Fill:

- `Resource` -> `Row`
- `Operation` -> `Get`
- `Data table` -> `telegram_bot_sessions`

Filter:

- `chat_id` `eq` `={{$json.chatId}}`

## 21. `Poll Backend Status`

Type:

- `HTTP Request`

Fill:

- `Method` -> `GET`
- `URL` -> `={{$env.BACKEND_BASE_URL + '/api/v1/invoice-review/bot/uploads/' + ($json.data?.[0]?.backend_upload_id || '')}}`

## 22. `Map Status Outcome`

Type:

- `Code`

Paste:

```javascript
const source = $json;
let text = source.message || 'Статус обновлен.';
if (source.review_id) {
  text += `\nReview ID: ${source.review_id}`;
}
if (source.result_code) {
  text += `\nРезультат: ${source.result_code}`;
}
if (source.error_text) {
  text += `\nОшибка: ${source.error_text}`;
}
return [{ json: { ...source, replyText: text } }];
```

## 23. `Reply Status`

Type:

- `Telegram`

Fill:

- `Chat ID` -> `={{$item(0).$node['Normalize Update'].json.chatId}}`
- `Text` -> `={{$json.replyText}}`

## 24. `Reset Session`

Type:

- `Data Table`

Fill:

- `Resource` -> `Row`
- `Operation` -> `Delete`
- `Data table` -> `telegram_bot_sessions`

Filter:

- `chat_id` `eq` `={{$json.chatId}}`

## 25. `Reply Reset`

Type:

- `Telegram`

Fill:

- `Chat ID` -> `={{$json.chatId}}`
- `Text` -> `Текущая сессия сброшена.`

## 26. `Reply Unknown Intent`

Type:

- `Telegram`

Fill:

- `Chat ID` -> `={{$json.chatId}}`
- `Text` -> `Не понял команду. Нажмите «Новый документ», отправьте файл накладной, либо используйте команды «Статус» и «Сбросить».`

## Connection order

Keep the branches exactly like this:

- `Route Intent[0]` -> `Start Session Store`
- `Route Intent[1]` -> `Load Session For File`
- `Route Intent[2]` -> `Load Session Finalize`
- `Route Intent[3]` -> `Load Session Status`
- `Route Intent[4]` -> `Reset Session`
- `Route Intent[5]` -> `Reply Unknown Intent`

## Practical warning

If a node shows `No input data`, that usually means:

- execute the previous nodes first
- or run the workflow from `Telegram Trigger`

That is normal for manual node inspection in `n8n`.
