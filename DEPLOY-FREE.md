# Korean–Uzbek Vocabulary Bot — v2 deployment

## Features
- Keeps the existing `/add`, `/addword`, `/list`, `/quiz`, `/quiz_ko`, and `/quiz_uz` commands.
- `/import` accepts pasted word pairs or uploaded `.txt` and `.csv` files.
- Imports up to 10,000 rows per import (file size limit 5 MB).
- Shows a preview and conservative local Korean spelling suggestions before saving. You must approve the import.
- Each Telegram user has a personal vocabulary deck. Existing words in that user's deck are skipped as duplicates.
- `/count` reports the current personal word count.

## Deploying to JustRunMy.App
1. Back up the existing database before redeploying. The default database file is `data/vocab.db`.
2. Open your app's storage/settings and confirm whether its filesystem is persistent across redeployments. If the platform provides a persistent disk, mount it at `/app/data` so `data/vocab.db` stays outside the replaceable app layer.
3. If the platform requires a separate persistent directory, copy the existing `vocab.db` into that directory first, then set `DATA_DIR` to that directory. Do not point `DATA_DIR` at an empty directory unless you intend to start with a fresh database.
4. Upload this ZIP as the app source.
5. Set environment variable `TELEGRAM_BOT_TOKEN` to your token from @BotFather. Never put the token in the source code or share it.
6. Optional: set `DATA_DIR` only to a real persistent directory provided by your host. If unset, the bot uses `/app/data/vocab.db`.
7. Start command: `sh start.sh` (or `pip install -r requirements.txt && python bot.py`).
8. Stop any other running instance of the same bot. With polling, run only one instance per bot token.
9. Test `/start`, `/count`, `/import`, upload a small test file, approve it, then run `/quiz`.

## Supported formats
TXT, one pair per line:

```text
배우다 — o‘rganmoq
마시다 — ichmoq
```

CSV, two columns with optional header:

```csv
Korean,Uzbek
배우다,o‘rganmoq
마시다,ichmoq
```

UTF-8 is recommended. Keep the Korean word in the first column and the Uzbek meaning in the second.

## Important spelling-check limitation
The offline checker catches a few known common mistakes and suggests close matches from a small local Korean vocabulary list. It is not a complete Korean dictionary, and it cannot reliably detect an incorrect Uzbek meaning for a correctly spelled Korean word. Review all suggestions and translations before approving. No external AI service or API key is used.

## Persistent database warning
The code keeps the database at the same default path (`data/vocab.db`) to remain compatible with the existing project. Code cannot force a hosting provider to preserve files when an app is redeployed. Verify persistent disk support in the host settings and keep an external backup before every redeployment.
