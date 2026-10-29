import random
import re
import unicodedata
from enum import Enum


class Direction(str, Enum):
    KO_TO_UZ = "ko_to_uz"
    UZ_TO_KO = "uz_to_ko"
    MIXED = "mixed"


def normalize_latin(text: str) -> str:
    text = text.strip().lower()
    text = unicodedata.normalize("NFKD", text)
    text = "".join(c for c in text if not unicodedata.combining(c))
    text = text.replace("’", "'").replace("`", "'")
    return re.sub(r"\s+", "", text)


def normalize_korean(text: str) -> str:
    return re.sub(r"\s+", "", text.strip())


def split_uzbek_meanings(uzbek: str) -> list[str]:
    parts: list[str] = []
    for chunk in re.split(r"[,/]", uzbek):
        chunk = chunk.strip()
        if chunk:
            parts.append(normalize_latin(chunk))
    return parts or [normalize_latin(uzbek)]


def pick_prompt_word(word: dict, direction: Direction) -> tuple[Direction, str, str, list[str]]:
    """Returns (direction, question, expected_display, acceptable_answers)."""
    korean = word["korean"]
    meanings = split_uzbek_meanings(word["uzbek"])

    if direction == Direction.MIXED:
        direction = random.choice([Direction.KO_TO_UZ, Direction.UZ_TO_KO])

    if direction == Direction.KO_TO_UZ:
        question = f"What is the Uzbek meaning of:\n\n🇰🇷 {korean}"
        acceptable = meanings
        expected = " / ".join(meanings)
    else:
        shown = random.choice(meanings)
        question = f"What is the Korean word for:\n\n🇺🇿 {shown}"
        acceptable = [normalize_korean(korean)]
        expected = korean

    return direction, question, expected, acceptable


def check_answer(user_text: str, direction: Direction, acceptable: list[str]) -> bool:
    if direction == Direction.KO_TO_UZ:
        answer = normalize_latin(user_text)
        return any(answer == alt for alt in acceptable)
    answer = normalize_korean(user_text)
    return answer in acceptable
