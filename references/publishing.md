# Optional publishing

Read this reference only when the user asks to upload generated outputs.

## Provider choice

Offer exactly these outcomes after local generation:

- Keep local only.
- Upload to an existing Flickr album owned by the authenticated account.
- Upload to a Google Photos album created by this integration.

Never infer upload permission from a generation request. Uploading is an external
write and requires a separate, explicit user choice.

## Mandatory preview

Use `scripts/publish_batch.py prepare` to create a JSON upload plan. Before any
upload, show the user:

- provider and authenticated account label;
- exact target album title and opaque ID;
- number and ordered filenames;
- for Flickr, a preview of each photo's description and the plan path containing its full prompt;
- Flickr privacy flags and search visibility; or
- for Google Photos, that the album is app-created and sharing is not controlled
  by the API.

The prepare command performs no network writes and prints a confirmation code.
Do not run `upload` until the user explicitly confirms that exact plan. Pass the
displayed code to `--confirm`; changed files invalidate the plan.

## Flickr

Required environment variables:

- `FLICKR_API_KEY`
- `FLICKR_API_SECRET`
- `FLICKR_OAUTH_TOKEN`
- `FLICKR_OAUTH_TOKEN_SECRET`

The OAuth token must grant `write` permission. The script uploads each file,
setting Flickr's photo `description` to that output's actual image-generation style
prompt, then appends its returned photo ID to the selected photoset. Supply a JSON
description manifest keyed by exact output filename; include the full preset or
custom prompt plus photo-specific clause used for that image. Do not infer prompts
from style names in filenames or silently leave a description empty. The prepare
step rejects missing or extra entries, and the confirmation code binds the full
descriptions. Default every photo
to private unless the user explicitly chooses broader visibility. Never print
credentials or place them in a plan, repository, command argument, or log.

Example preview:

```bash
python3 scripts/publish_batch.py prepare \
  --provider flickr --input '<output-directory>' \
  --account '<account-label>' \
  --album-id '<photoset-id>' --album-title '<verified-title>' \
  --descriptions '<batch-directory>/descriptions.json' \
  --public 0 --friends 0 --family 0 --hidden \
  --plan '<batch-directory>/flickr-upload-plan.json'
```

## Google Photos

Required environment variable:

- `GOOGLE_PHOTOS_ACCESS_TOKEN`

The OAuth token must grant `photoslibrary.appendonly`. Since March 31, 2025,
the Library API can add media only to albums created by this integration. It
cannot upload into an arbitrary pre-existing or shared album, and it cannot
manage sharing. If the user names such an album, explain the limitation and
offer to create/select an integration-owned album or keep the files local.

Example preview:

```bash
python3 scripts/publish_batch.py prepare \
  --provider google --input '<output-directory>' \
  --account '<account-label>' \
  --album-id '<app-created-album-id>' --album-title '<verified-title>' \
  --google-album-created-by-app \
  --plan '<batch-directory>/google-upload-plan.json'
```

## Execution and recovery

Execute only the provider shown in the confirmed plan:

```bash
python3 scripts/publish_batch.py upload \
  --plan '<plan.json>' --confirm '<confirmation-code>'
```

Stop on the first ambiguous failure. Report which filenames completed and which
did not. Do not automatically retry a whole batch because that can duplicate
uploads. A failed Flickr album insertion may leave the photo in the user's
photostream; report its returned photo ID. Google upload tokens expire and should
never be persisted in the plan.
