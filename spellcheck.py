"""Conservative offline Korean typo suggestions for vocabulary imports.

This deliberately does not guess Uzbek translations or silently rewrite entries.
Suggestions are shown for user approval before anything is saved.
"""
from difflib import get_close_matches

# Known high-confidence corrections seen in common learner lists.
EXACT_CORRECTIONS = {
    "하루조일": "하루 종일",
    "크가 크다": "키가 크다",
    "잠을 자다": "잠을 자다",
}

# A modest local vocabulary list for conservative nearest-match suggestions.
# This is not a complete Korean dictionary and cannot verify a translation's meaning.
KNOWN_KOREAN = {
    "가다", "가르치다", "간호사", "공부하다", "과일", "기차", "김치", "나중에",
    "낮", "늦다", "도와주다", "떨어지다", "마시다", "머리", "물", "배우다",
    "방학", "보고서", "불편하다", "사고가 나다", "술", "시험", "싸우다",
    "어제", "음식", "일하다", "잠시", "잠을 자다", "제출하다", "점", "집",
    "집안일", "집중하다", "처음", "차", "책", "키가 크다", "표", "폭발하다",
    "피곤하다", "하루 종일", "학교", "회사", "회사를 그만두다", "친구", "전화하다",
    "버튼을 누르다", "놓다", "놓치다", "핸드폰", "기다리다", "만나다", "먹다",
    "보다", "사다", "쓰다", "읽다", "오다", "하다", "좋다", "크다", "작다",
    "빠르다", "느리다", "아프다", "쉽다", "어렵다", "덥다", "춥다", "날씨",
    "시간", "오늘", "내일", "어제", "친구", "가족", "선생님", "학생", "회사원",
    "의사", "간호사", "한국어", "우즈베크어", "공항", "병원", "은행", "식당",
    "도서관", "지하철", "버스", "자동차", "비행기", "여행", "일", "주말",
    "월요일", "화요일", "수요일", "목요일", "금요일", "토요일", "일요일",
}


def suggest_korean_correction(korean: str) -> str | None:
    original = korean.strip()
    if original in EXACT_CORRECTIONS:
        fixed = EXACT_CORRECTIONS[original]
        return fixed if fixed != original else None
    # Ignore short words: fuzzy matching them is too likely to create false positives.
    if len(original.replace(" ", "")) < 4:
        return None
    compact = original.replace(" ", "")
    candidates = [w for w in KNOWN_KOREAN if w.replace(" ", "") != compact]
    matches = get_close_matches(compact, [w.replace(" ", "") for w in candidates], n=1, cutoff=0.84)
    if not matches:
        return None
    match_compact = matches[0]
    # Restore the canonical spaced form from the dictionary.
    for candidate in candidates:
        if candidate.replace(" ", "") == match_compact:
            return candidate
    return None
