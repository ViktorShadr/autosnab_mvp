# Telegram Bot MVP — Cloud n8n Setup Guide

Companion to `n8n/telegram-bot-mvp.workflow.json` and
`docs/wiki/telegram-bot-cloud-n8n-plan.md`. This workflow is a stateless
Telegram router: it holds no session/draft data itself — everything about
"which document is this page part of" lives in the backend
(`ingestion_uploads`, `collecting` status), keyed by `chat_id`.

This JSON was authored by hand against the current backend contract and has
**not** been test-imported into a live n8n instance yet (no live n8n access
from this environment). Import it, then work through the checklist below —
n8n will visually flag any node whose parameters didn't map cleanly, and this
guide tells you what the intended value is so you can fix it in a few clicks.

## 1. Prerequisites

- Backend running locally via `docker compose --profile public-tunnel up --build`
  (see `docker-compose.yml`), with `NGROK_AUTHTOKEN` and a strong
  `BOT_API_SHARED_SECRET` set in `.env`.
- Current public URL: `python3 scripts/get_ngrok_public_url.py`.
- A Telegram bot token from `@BotFather`.

## 2. Import

In cloud n8n: **Workflows → Import from File** → select
`telegram-bot-mvp.workflow.json`. It imports as an inactive draft named
`Autosnab Telegram Bot MVP (Cloud n8n)`.

## 3. Credentials to create

Every node that talks to Telegram or the backend references a credential by
name; n8n will show these as "Credential not found" until you attach your
own. Create these two, then reselect them on each node listed:

### Telegram API credential — name it `Telegram Bot`

- Type: **Telegram API**.
- Access Token: the `@BotFather` bot token.
- Attach to: **Telegram Trigger**, **Get Telegram File**, **Send Reply**,
  **Send Stage Update**.

### HTTP Header Auth credential — name it `Bot API Key`

- Type: **Header Auth**.
- Name: `X-Bot-Api-Key`.
- Value: the same string as `.env`'s `BOT_API_SHARED_SECRET`.
- Attach to every `HTTP Request` node: **Send Page To Backend**,
  **Finalize Draft**, **Check Upload Status**, **Check Draft Status**,
  **Check Latest Upload**, **Reset Draft**.
- If `BOT_API_SHARED_SECRET` is left empty in `.env` (local-only testing),
  the backend skips the check — you can leave the header value blank too,
  but do this only while `ngrok` is not exposing the backend publicly.

## 4. Workflow Config node

Open the **Workflow Config** node (first Code node after the trigger) and
edit the `backendBaseUrl` literal:

```js
backendBaseUrl: 'https://REPLACE-WITH-NGROK-URL',
```

Replace with the current `ngrok` HTTPS URL. This is the **only** place the
backend URL is hardcoded — everything else references it via
`{{ $('Workflow Config').item.json.backendBaseUrl }}`. When `ngrok` restarts
with a new URL, this is the only node you need to touch.

`maxPollAttempts` (default `24`, ~2 minutes at 5s/attempt) controls how long
the bot waits for processing to finish before telling the user to check
`Статус` later — raise it if OpenAI/MinerU runs are consistently slower than
that on your machine.

## 5. Points to double-check after import (hand-authored JSON, not yet live-tested)

n8n is generally forgiving about re-importing older parameter shapes and
will show a small warning icon on any node it had to adjust. Check these
first if something looks off:

- **Send Page To Backend** (multipart body): confirm the `file` field shows
  as *Body Parameter → Parameter Type: n8n Binary File → Input Data Field
  Name: `data`*, and the three text fields (`chat_id`, `source_user_id`,
  `source_username`) show as Form Data. If the binary field didn't map,
  delete and re-add it with those exact settings — this uploads whatever
  `Get Telegram File` downloaded into its `data` binary property.
- **Get Telegram File**: resource `File`, operation `Get`, File ID
  `={{$json.file_id}}`. Output binary property should be `data` (n8n's
  default for this node) — that's what `Send Page To Backend` reads.
- **Finalize Draft** / **Check Latest Upload**: both use *On Error → Continue
  (using error output)*, giving them two outputs (success / error) instead of
  a separate `IF` node. Confirm this setting survived import; if not, set it
  manually on the node's **Settings** tab.
- Any `IF` node: each has exactly one condition, written as a full boolean
  expression compared to `true` (e.g. `{{$json.intent === 'file'}}` equals
  `true`), rather than n8n's built-in string/exists operators. This was a
  deliberate choice for stability across n8n versions — don't need to change
  it, just know why it looks that way.
- **Send Reply** (reply keyboard): the JSON ships with **no** reply-keyboard
  parameters — an earlier attempt to hand-author them (`replyMarkup` /
  `replyKeyboard` as top-level node parameters) caused n8n to reject the
  whole import with `Could not find property option`, because those fields
  actually live nested under **Additional Fields**, not at the top level of
  the node. Rather than guess the exact nesting again, add the keyboard
  yourself in the editor (2 minutes, and the UI can't produce invalid JSON):
  1. Open the **Send Reply** node.
  2. Under **Additional Fields**, click **Add Field** → choose **Reply
     Markup**, set it to **Reply Keyboard**.
  3. In the **Reply Keyboard** section, add two rows: row 1 = `Готово`,
     `Статус`; row 2 = `Сбросить`.
  4. Optionally enable **Resize Keyboard**.
  `Normalize Update` already accepts the plain text `Готово` / `Статус` /
  `Сбросить` (case-insensitive) whether it arrives as a typed message or a
  tapped keyboard button, so no other node needs to change once this is set.

## 6. Progress messages while a document is processing

So the operator never wonders if the bot "hung", the poll loop
(`Prepare Poll → Wait Before Poll → Check Upload Status → If Poll Done →
Compute Stage → If Stage Changed → Set Stage Reply Text → Send Stage
Update`) sends one extra Telegram message every time the backend's
`pipeline_logs` move into a new coarse stage, in this order:

1. `Документ принят в обработку.` — sent immediately after `Готово`
   (via **Reply Processing Started**, before the poll loop even starts).
2. `Выгружаем данные из скана...` — once OCR/MinerU/image-prep stages start.
3. `Обрабатываем данные через ИИ...` — once the OpenAI/reference-mapping
   stages start.
4. `Загружаем данные в таблицу...` — once the Google Sheets write starts.
5. The final result message (supplier/invoice/sum/sheet link, or the
   duplicate/error/needs-review text) once `completed` is `true`.

**Compute Stage** derives the current coarse stage from the *last* entry in
`pipeline_logs` and only lets a message through when the stage actually
changed since the last one sent (tracked via `Set Stage Reply Text`'s output,
read back with `$('Set Stage Reply Text')` — the standard n8n trick for
carrying a value across loop iterations without any external session
storage). If processing is fast enough that a stage is skipped between two
5-second polls, that message is simply never sent — this is expected, not a
bug.

The reply keyboard is only attached to **Send Reply** (the final-answer
node); it doesn't need to be repeated on **Send Stage Update**, since a
Telegram reply keyboard stays visible across messages once shown once.

## 7. Activate and test

Activate the workflow (top-right toggle), set the Telegram webhook if not
done automatically by the trigger node, then run the smoke tests from
`docs/wiki/telegram-bot-cloud-n8n-plan.md`:

1. Single photo → `Готово` → result with summary + sheet link.
2. Two photos → `Готово` → one logical document, not two.
3. Re-send the same document → duplicate result.
4. Unsupported file → clear rejection, draft untouched.
5. `Статус` mid-collection → correct page count.
6. `Сбросить` mid-collection → next file starts a fresh draft.
7. Stop the Docker backend mid-processing → `Статус` still returns the last
   durable state instead of a workflow error.
8. Restart `ngrok` → update only `Workflow Config` → bot works again.
