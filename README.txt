Korean–Uzbek Vocabulary Telegram Bot — lesson edition

Features
- /lessons lists lessons in order and shows progress.
- /lesson <number> displays a lesson's vocabulary.
- /lessonquiz <number> [mixed|ko|uz] tests only that lesson.
- /progress shows completed lessons. A lesson is completed at 75% or higher.
- /quiz, /quiz_ko, /quiz_uz still quiz the user's personal vocabulary deck.
- Existing personal words/import features remain available.

Vocabulary data is bundled at data/lessons_vocabulary.csv. It contains 1,086 extracted entries across 21 populated lessons (1–15 and 17–22; lesson 16 is absent from the supplied CSV). Entries retain topic, word category, and source page fields. The source CSV flags translations as automatically extracted and not fully manually verified; review before treating every translation as authoritative.

Run locally with Python 3.14 or newer:

1. Set `TELEGRAM_BOT_TOKEN` to the token from @BotFather.
2. Install dependencies: `python -m pip install -r requirements.txt`
3. Start the bot: `python bot.py`

The bot uses polling, so run only one local or deployed instance for the same token.
