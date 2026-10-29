import csv
import io
import logging
import os
import random
import re

from dotenv import load_dotenv
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram import BotCommand
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)

from data.day2 import DAY2_LABEL
from quiz import Direction, check_answer, pick_prompt_word
import storage
from spellcheck import suggest_korean_correction

load_dotenv()
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)
logging.getLogger("httpx").setLevel(logging.WARNING)

ADD_KOREAN, ADD_UZBEK, IMPORT_INPUT, IMPORT_REVIEW = range(4)
QUIZ_ANSWER = 10
MAX_IMPORT_BYTES = 5 * 1024 * 1024
MAX_IMPORT_ROWS = 10000


def user_id(update: Update) -> int:
    return update.effective_user.id


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    uid = user_id(update)
    storage.ensure_day2_seeded(uid)
    count = storage.count_words(uid)
    await update.effective_message.reply_text(
        "Korean ↔ Uzbek vocabulary bot\n\n"
        f"Your personal deck has {count} words (including «{DAY2_LABEL}»).\n\n"
        "Commands:\n"
        "/add — add one word step by step\n"
        "/addword <Korean> <Uzbek> — quick add\n"
        "/import — import a .txt/.csv file or paste a word list\n"
        "/list — show your words\n"
        "/count — count your words\n"
        "/quiz — mixed Korean↔Uzbek quiz\n"
        "/quiz_ko — Korean → Uzbek only\n"
        "/quiz_uz — Uzbek → Korean only\n"
        "/lessons — list vocabulary lessons\n"
        "/lesson <number> — study words in a lesson\n"
        "/lessonquiz <number> [mixed|ko|uz] — test one lesson\n"
        "/progress — view completed lessons\n"
        "/stop — end current quiz\n"
        "/cancel — cancel adding/importing\n"
        "/help — show this message\n\n"
        "Imports are checked before saving. Korean spelling suggestions are local and conservative;"
        " please review translations yourself because meaning cannot be guaranteed automatically."
    )


async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await start(update, context)


async def count_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    storage.ensure_day2_seeded(user_id(update))
    await update.effective_message.reply_text(f"You have {storage.count_words(user_id(update))} words in your personal deck.")


async def list_words(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    uid = user_id(update)
    storage.ensure_day2_seeded(uid)
    words = storage.list_words(uid)
    if not words:
        await update.effective_message.reply_text("No words yet. Use /add, /addword, or /import.")
        return
    lines = []
    current_deck = None
    for word in words:
        if word["deck"] != current_deck:
            current_deck = word["deck"]
            lines.append(f"\n📚 {current_deck}")
        lines.append(f"• {word['korean']} — {word['uzbek']}")
    output = "\n".join(lines).strip()
    if len(output) > 4000:
        output = output[:3900] + "\n… List shortened. Use /count for the total."
    await update.effective_message.reply_text(output)


async def add_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.effective_message.reply_text("Send the Korean word or phrase:")
    return ADD_KOREAN


async def add_korean(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data["new_korean"] = update.effective_message.text.strip()
    await update.effective_message.reply_text("Send the Uzbek translation:")
    return ADD_UZBEK


async def add_uzbek(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    uid = user_id(update)
    korean = context.user_data.get("new_korean", "").strip()
    uzbek = update.effective_message.text.strip()
    if not korean or not uzbek:
        await update.effective_message.reply_text("Cancelled — missing text. Try /add again.")
        return ConversationHandler.END
    ok = storage.add_word(uid, korean, uzbek, deck="my words")
    await update.effective_message.reply_text(
        f"Added: {korean} — {uzbek}" if ok else f"Already in your list: {korean} (same Korean in this deck)."
    )
    context.user_data.pop("new_korean", None)
    return ConversationHandler.END


def _split_pair(line: str) -> tuple[str, str] | None:
    line = line.strip()
    if not line:
        return None
    # Support numbered lists such as "1. 배우다 - o'rganmoq".
    line = re.sub(r"^\s*\d+[.)]\s*", "", line)
    separators = ("—", "–", "\t", " - ", " : ", "-")
    for sep in separators:
        if sep in line:
            korean, uzbek = line.split(sep, 1)
            korean, uzbek = korean.strip(), uzbek.strip()
            if korean and uzbek:
                return korean, uzbek
    return None


def parse_text_list(text: str) -> tuple[list[tuple[str, str]], int]:
    pairs: list[tuple[str, str]] = []
    invalid = 0
    for line in text.splitlines():
        if not line.strip():
            continue
        pair = _split_pair(line)
        if pair:
            pairs.append(pair)
        else:
            invalid += 1
    return pairs, invalid


def parse_csv_list(text: str) -> tuple[list[tuple[str, str]], int]:
    pairs: list[tuple[str, str]] = []
    invalid = 0
    try:
        rows = list(csv.reader(io.StringIO(text)))
    except csv.Error:
        return [], max(1, len(text.splitlines()))
    if not rows:
        return [], 0

    first = [cell.strip().casefold() for cell in rows[0]]
    has_header = len(first) >= 2 and first[0] in {"korean", "한국어", "korean word", "word"} and first[1] in {"uzbek", "o'zbek", "uzbekcha", "translation", "meaning"}
    if has_header:
        rows = rows[1:]

    for row in rows:
        if not row or all(not cell.strip() for cell in row):
            continue
        if len(row) >= 2 and row[0].strip() and row[1].strip():
            pairs.append((row[0].strip(), row[1].strip()))
        elif len(row) == 1:
            pair = _split_pair(row[0])
            if pair:
                pairs.append(pair)
            else:
                invalid += 1
        else:
            invalid += 1
    return pairs, invalid


def _review_import(context: ContextTypes.DEFAULT_TYPE, uid: int, pairs: list[tuple[str, str]], invalid: int, source_name: str) -> tuple[int, int]:
    if len(pairs) > MAX_IMPORT_ROWS:
        raise ValueError(f"This file has {len(pairs)} rows. The maximum per import is {MAX_IMPORT_ROWS}.")
    # Keep original pairs and proposed pairs separate so the user can choose.
    proposed: list[tuple[str, str]] = []
    corrections: list[tuple[str, str, str]] = []
    for korean, uzbek in pairs:
        suggestion = suggest_korean_correction(korean)
        if suggestion and suggestion != korean:
            corrections.append((korean, suggestion, uzbek))
            proposed.append((suggestion, uzbek))
        else:
            proposed.append((korean, uzbek))
    context.user_data["pending_import"] = {
        "original": pairs,
        "proposed": proposed,
        "invalid": invalid,
        "corrections": corrections,
        "source": source_name,
    }
    existing = storage.existing_korean(uid)
    seen: set[str] = set()
    duplicates = 0
    for korean, _ in proposed:
        key = korean.strip().casefold()
        if key in existing or key in seen:
            duplicates += 1
        seen.add(key)
    return len(corrections), duplicates


async def import_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.effective_message.reply_text(
        "Send a .txt or .csv file, or paste the vocabulary directly.\n\n"
        "TXT example (one pair per line):\n배우다 — o‘rganmoq\n마시다 — ichmoq\n\n"
        "CSV example: two columns named Korean,Uzbek (a header is optional).\n"
        "I will show a preview and possible Korean spelling corrections before saving anything.\n"
        "Maximum file size: 5 MB; maximum 10,000 rows per import. Send /cancel to stop."
    )
    return IMPORT_INPUT


async def _show_import_review(update: Update, context: ContextTypes.DEFAULT_TYPE, pairs: list[tuple[str, str]], invalid: int, source_name: str) -> int:
    if not pairs:
        await update.effective_message.reply_text("I couldn't find valid Korean–Uzbek pairs. Check the format and try /import again.")
        return IMPORT_INPUT
    try:
        correction_count, duplicate_count = _review_import(context, user_id(update), pairs, invalid, source_name)
    except ValueError as exc:
        await update.effective_message.reply_text(str(exc))
        return IMPORT_INPUT

    pending = context.user_data["pending_import"]
    preview_pairs = pending["proposed"]
    lines = [f"Import review — {source_name}", f"Pairs found: {len(pairs)}", f"Possible duplicates: {duplicate_count}", f"Invalid lines skipped: {invalid}", f"Korean spelling suggestions: {correction_count}", ""]
    if pending["corrections"]:
        lines.append("Suggested corrections (review carefully):")
        for old, new, uzbek in pending["corrections"][:12]:
            lines.append(f"• {old} → {new} — {uzbek}")
        if len(pending["corrections"]) > 12:
            lines.append(f"… and {len(pending['corrections']) - 12} more suggestions")
        lines.append("")
    lines.append("Preview of entries to save:")
    for korean, uzbek in preview_pairs[:12]:
        lines.append(f"• {korean} — {uzbek}")
    if len(preview_pairs) > 12:
        lines.append(f"… and {len(preview_pairs) - 12} more entries")
    lines.extend(["", "Nothing has been saved yet. Choose an option below."])
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("Approve suggestions & save", callback_data="vocab_import:corrected")],
        [InlineKeyboardButton("Save original spellings", callback_data="vocab_import:original")],
        [InlineKeyboardButton("Cancel import", callback_data="vocab_import:cancel")],
    ])
    await update.effective_message.reply_text("\n".join(lines), reply_markup=keyboard)
    return IMPORT_REVIEW


async def import_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = update.effective_message.text or ""
    pairs, invalid = parse_text_list(text)
    return await _show_import_review(update, context, pairs, invalid, "pasted text")


async def import_document(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    document = update.effective_message.document
    if not document:
        await update.effective_message.reply_text("Please upload a .txt or .csv file.")
        return IMPORT_INPUT
    if document.file_size and document.file_size > MAX_IMPORT_BYTES:
        await update.effective_message.reply_text("That file is over 5 MB. Please upload a smaller .txt or .csv file.")
        return IMPORT_INPUT
    filename = (document.file_name or "vocabulary.txt").lower()
    if not filename.endswith((".txt", ".csv")):
        await update.effective_message.reply_text("Unsupported file type. Please upload a .txt or .csv file.")
        return IMPORT_INPUT
    remote_file = await context.bot.get_file(document.file_id)
    raw = bytes(await remote_file.download_as_bytearray())
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        await update.effective_message.reply_text("I couldn't read this file as UTF-8. Save it as UTF-8 and upload again.")
        return IMPORT_INPUT
    if filename.endswith(".csv"):
        pairs, invalid = parse_csv_list(text)
    else:
        pairs, invalid = parse_text_list(text)
    return await _show_import_review(update, context, pairs, invalid, filename)


async def import_decision(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    pending = context.user_data.get("pending_import")
    action = (query.data or "").split(":", 1)[-1]
    if action == "cancel":
        context.user_data.pop("pending_import", None)
        await query.edit_message_text("Import cancelled. No words were saved.")
        return ConversationHandler.END
    if not pending:
        await query.edit_message_text("This import preview has expired. Please send /import again.")
        return ConversationHandler.END
    pairs = pending["proposed"] if action == "corrected" else pending["original"]
    added, skipped = storage.add_words_bulk(user_id(update), pairs, deck="my words")
    invalid = pending.get("invalid", 0)
    context.user_data.pop("pending_import", None)
    await query.edit_message_text(
        "Import complete!\n"
        f"Added: {added}\n"
        f"Skipped (duplicates/empty): {skipped}\n"
        f"Invalid lines ignored: {invalid}\n\n"
        f"Your personal deck now contains {storage.count_words(user_id(update))} words.\n"
        "Use /quiz to practise or /list to view your vocabulary."
    )
    return ConversationHandler.END


async def add_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data.pop("new_korean", None)
    context.user_data.pop("pending_import", None)
    await update.effective_message.reply_text("Cancelled. Nothing pending was saved.")
    return ConversationHandler.END


async def addword_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if len(context.args) < 2:
        await update.effective_message.reply_text("Usage: /addword <Korean> <Uzbek translation>")
        return
    korean = context.args[0]
    uzbek = " ".join(context.args[1:])
    ok = storage.add_word(user_id(update), korean, uzbek, deck="my words")
    await update.effective_message.reply_text(f"Added: {korean} — {uzbek}" if ok else f"Already have: {korean}")


def load_lessons() -> dict[int, list[dict]]:
    path = os.path.join(os.path.dirname(__file__), "data", "lessons_vocabulary.csv")
    lessons: dict[int, list[dict]] = {}
    with open(path, encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            try:
                lesson_id = int(row["Dars"].strip())
            except (ValueError, KeyError):
                continue
            korean = row.get("Koreyscha", "").strip()
            uzbek = row.get("O‘zbekcha (tahrirlangan)", "").strip()
            if korean and uzbek:
                lessons.setdefault(lesson_id, []).append({
                    "korean": korean, "uzbek": uzbek, "lesson_id": lesson_id,
                    "topic": row.get("Mavzu", "").strip(),
                    "category": row.get("So‘z turkumi", "").strip(),
                    "source_page": row.get("Manba sahifasi", "").strip(),
                })
    return lessons

LESSONS = load_lessons()

async def lessons_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    progress = storage.get_lesson_progress(user_id(update))
    lines = ["📚 Korean–Uzbek lessons", "Send /lesson 1 to study a lesson or /lessonquiz 1 mixed to test it.", ""]
    for lesson_id in sorted(LESSONS):
        info = progress.get(lesson_id, {})
        status = "✅ completed" if info.get("completed") else (f"attempts: {info.get('attempts', 0)}" if info.get("attempts") else "not started")
        topic = LESSONS[lesson_id][0].get("topic", f"Lesson {lesson_id}").replace(f"{lesson_id}-dars — ", "")
        lines.append(f"{lesson_id}. {topic} — {len(LESSONS[lesson_id])} words ({status})")
    lines.append("\nNote: the vocabulary list was extracted automatically and some Uzbek meanings/spellings may need review.")
    await update.effective_message.reply_text("\n".join(lines))

async def lesson_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not context.args or not context.args[0].isdigit():
        await update.effective_message.reply_text("Usage: /lesson <number>\nExample: /lesson 1")
        return
    lesson_id = int(context.args[0])
    words = LESSONS.get(lesson_id)
    if not words:
        await update.effective_message.reply_text(f"Lesson {lesson_id} was not found in the vocabulary file.")
        return
    lines = [f"📘 Lesson {lesson_id} — {len(words)} words", words[0].get("topic", ""), ""]
    for i, word in enumerate(words, 1):
        lines.append(f"{i}. {word['korean']} — {word['uzbek']}")
    lines.append(f"\nWhen ready, try /lessonquiz {lesson_id} mixed (or ko / uz).")
    output = "\n".join(lines)
    # Telegram message limit; split long lessons into safe chunks.
    for start in range(0, len(output), 3800):
        await update.effective_message.reply_text(output[start:start+3800])

async def progress_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    progress = storage.get_lesson_progress(user_id(update))
    completed = sum(1 for item in progress.values() if item.get("completed"))
    await update.effective_message.reply_text(
        f"Lesson progress: {completed}/{len(LESSONS)} completed (75% or higher).\n" +
        "\n".join(f"Lesson {n}: {'✅ completed' if progress.get(n, {}).get('completed') else 'not completed'}" for n in sorted(LESSONS))
    )

async def lesson_quiz(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if not context.args or not context.args[0].isdigit():
        await update.effective_message.reply_text("Usage: /lessonquiz <number> [mixed|ko|uz]\nExample: /lessonquiz 1 ko")
        return ConversationHandler.END
    lesson_id = int(context.args[0])
    words = LESSONS.get(lesson_id)
    if not words:
        await update.effective_message.reply_text(f"Lesson {lesson_id} was not found.")
        return ConversationHandler.END
    mode = context.args[1].lower() if len(context.args) > 1 else "mixed"
    directions = {"mixed": Direction.MIXED, "ko": Direction.KO_TO_UZ, "uz": Direction.UZ_TO_KO}
    if mode not in directions:
        await update.effective_message.reply_text("Direction must be mixed, ko, or uz.")
        return ConversationHandler.END
    quiz_words = [dict(word) for word in words]
    random.shuffle(quiz_words)
    context.user_data["_quiz_uid"] = user_id(update)
    context.user_data["quiz"] = {"direction_mode": directions[mode], "words": quiz_words, "index": 0, "correct": 0, "asked": 0, "lesson_id": lesson_id}
    await update.effective_message.reply_text(f"Starting Lesson {lesson_id} quiz ({mode}). Pass mark: 75%.")
    return await _send_next_question(update, context)

def _start_quiz(context: ContextTypes.DEFAULT_TYPE, direction: Direction) -> None:
    uid = context.user_data.get("_quiz_uid")
    words = storage.get_all_words(uid)
    random.shuffle(words)
    context.user_data["quiz"] = {"direction_mode": direction, "words": words, "index": 0, "correct": 0, "asked": 0}


async def _send_next_question(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    quiz = context.user_data.get("quiz")
    if not quiz:
        return ConversationHandler.END
    idx, words = quiz["index"], quiz["words"]
    if idx >= len(words):
        correct, asked = quiz["correct"], quiz["asked"]
        lesson_id = quiz.get("lesson_id")
        if lesson_id is not None:
            storage.record_lesson_result(context.user_data.get("_quiz_uid", user_id(update)), lesson_id, correct, asked)
        await update.effective_message.reply_text(
            f"Quiz finished.\nScore: {correct}/{asked}" + (f" ({100 * correct // asked}%)" if asked else "") +
            ("\n🎉 Lesson completed!" if lesson_id is not None and asked and correct / asked >= 0.75 else ("\nReview this lesson and try again to reach 75%." if lesson_id is not None else ""))
        )
        context.user_data.pop("quiz", None)
        return ConversationHandler.END
    word = words[idx]
    direction, question, _, acceptable = pick_prompt_word(word, quiz["direction_mode"])
    quiz["current"] = {"direction": direction, "acceptable": acceptable, "expected": word}
    quiz["asked"] += 1
    await update.effective_message.reply_text(question + "\n\n(Type /stop to end, /skip to skip)")
    return QUIZ_ANSWER


async def quiz_start(update: Update, context: ContextTypes.DEFAULT_TYPE, direction: Direction) -> int:
    uid = user_id(update)
    storage.ensure_day2_seeded(uid)
    if storage.count_words(uid) == 0:
        await update.effective_message.reply_text("Add words first with /add, /addword, or /import.")
        return ConversationHandler.END
    context.user_data["_quiz_uid"] = uid
    _start_quiz(context, direction)
    await update.effective_message.reply_text("Starting quiz…")
    return await _send_next_question(update, context)


async def quiz_mixed(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    return await quiz_start(update, context, Direction.MIXED)


async def quiz_ko(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    return await quiz_start(update, context, Direction.KO_TO_UZ)


async def quiz_uz(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    return await quiz_start(update, context, Direction.UZ_TO_KO)


async def quiz_answer(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    quiz = context.user_data.get("quiz")
    if not quiz or "current" not in quiz:
        return ConversationHandler.END
    current = quiz["current"]
    user_text = update.effective_message.text.strip()
    if check_answer(user_text, current["direction"], current["acceptable"]):
        quiz["correct"] += 1
        word = current["expected"]
        meanings = word.get("uzbek", "")
        await update.effective_message.reply_text(f"✅ Correct!\nMeanings: {meanings}")
    else:
        word = current["expected"]
        answer = word["uzbek"] if current["direction"] == Direction.KO_TO_UZ else word["korean"]
        await update.effective_message.reply_text(f"❌ Not quite. Answer: {answer}")
    quiz["index"] += 1
    return await _send_next_question(update, context)


async def quiz_skip(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    quiz = context.user_data.get("quiz")
    if not quiz or "current" not in quiz:
        await update.effective_message.reply_text("No active quiz.")
        return ConversationHandler.END
    word = quiz["current"]["expected"]
    answer = word["uzbek"] if quiz["current"]["direction"] == Direction.KO_TO_UZ else word["korean"]
    await update.effective_message.reply_text(f"Skipped. Answer: {answer}")
    quiz["index"] += 1
    return await _send_next_question(update, context)


async def quiz_stop(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    quiz = context.user_data.pop("quiz", None)
    if quiz:
        correct, asked = quiz.get("correct", 0), quiz.get("asked", 0)
        await update.effective_message.reply_text(f"Quiz stopped. Score so far: {correct}/{asked}")
    else:
        await update.effective_message.reply_text("No active quiz.")
    return ConversationHandler.END


async def configure_bot_menu(application: Application) -> None:
    await application.bot.set_my_commands([
        BotCommand("start", "Start the vocabulary bot"),
        BotCommand("help", "Show help and commands"),
        BotCommand("add", "Add a word step by step"),
        BotCommand("addword", "Quickly add a word"),
        BotCommand("import", "Import vocabulary"),
        BotCommand("list", "Show your words"),
        BotCommand("count", "Count your words"),
        BotCommand("quiz", "Mixed vocabulary quiz"),
        BotCommand("quiz_ko", "Korean to Uzbek quiz"),
        BotCommand("quiz_uz", "Uzbek to Korean quiz"),
        BotCommand("lessons", "List vocabulary lessons"),
        BotCommand("lesson", "Study a lesson"),
        BotCommand("lessonquiz", "Quiz a lesson"),
        BotCommand("progress", "Show lesson progress"),
        BotCommand("stop", "Stop the current quiz"),
        BotCommand("cancel", "Cancel the current action"),
    ])


def main() -> None:
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not token:
        raise SystemExit("Set TELEGRAM_BOT_TOKEN in the environment (see DEPLOY-FREE.md)")
    app = Application.builder().token(token).post_init(configure_bot_menu).build()

    add_conv = ConversationHandler(
        entry_points=[CommandHandler("add", add_start)],
        states={
            ADD_KOREAN: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_korean)],
            ADD_UZBEK: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_uzbek)],
        },
        fallbacks=[CommandHandler("cancel", add_cancel)],
        allow_reentry=True,
    )
    import_conv = ConversationHandler(
        entry_points=[CommandHandler("import", import_start)],
        states={
            IMPORT_INPUT: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, import_text),
                MessageHandler(filters.Document.ALL, import_document),
            ],
            IMPORT_REVIEW: [CallbackQueryHandler(import_decision, pattern=r"^vocab_import:(corrected|original|cancel)$")],
        },
        fallbacks=[CommandHandler("cancel", add_cancel)],
        allow_reentry=True,
    )
    quiz_conv = ConversationHandler(
        entry_points=[
            CommandHandler("lessonquiz", lesson_quiz),
            CommandHandler("quiz", quiz_mixed),
            CommandHandler("quiz_ko", quiz_ko),
            CommandHandler("quiz_uz", quiz_uz),
        ],
        states={QUIZ_ANSWER: [MessageHandler(filters.TEXT & ~filters.COMMAND, quiz_answer)]},
        fallbacks=[CommandHandler("stop", quiz_stop), CommandHandler("skip", quiz_skip)],
        allow_reentry=True,
    )
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CommandHandler("count", count_cmd))
    app.add_handler(CommandHandler("list", list_words))
    app.add_handler(CommandHandler("lessons", lessons_cmd))
    app.add_handler(CommandHandler("lesson", lesson_cmd))
    app.add_handler(CommandHandler("progress", progress_cmd))
    app.add_handler(CommandHandler("addword", addword_cmd))
    app.add_handler(add_conv)
    app.add_handler(import_conv)
    app.add_handler(quiz_conv)
    app.add_handler(CommandHandler("stop", quiz_stop))
    logger.info("Bot starting… Database path: %s", storage.DB_PATH)
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
