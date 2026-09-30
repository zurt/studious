"""The learner's study profile: JLPT level and preferred answer length.

Stored in `preferences.json` (set from the Settings modal) and rendered into
the exercise-completion prompt so answers sit at, or one step above, the
learner's level, and Japanese answers are sized to what the learner could
realistically produce. Answer length governs only the Japanese the model
writes; the English explanations are unaffected.
"""
from __future__ import annotations

from typing import Any

from . import preferences

LEVELS = ("N5", "N4", "N3", "N2", "N1")
ANSWER_LENGTHS = ("brief", "standard", "detailed")
DEFAULT_ANSWER_LENGTH = "brief"
MAX_NOTE_LENGTH = 200

_EXAMPLE_COUNT = {"brief": 2, "standard": 3, "detailed": 3}
_NUMBER_WORDS = {2: "two", 3: "three"}
_QUESTION_LENGTH = {
    "brief": (
        "one short sentence (two if the question asks two things), the "
        "answer a learner could realistically write"
    ),
    "standard": "usually one to three sentences",
    "detailed": (
        "two to four sentences, fuller than a learner would write, showing "
        "how a fluent speaker would answer"
    ),
}


def current() -> dict[str, Any]:
    """The saved profile, with invalid or missing values normalized."""
    prefs = preferences.load()
    level = prefs.get("learner_level")
    length = prefs.get("answer_length")
    return {
        "level": level if level in LEVELS else None,
        "note": str(prefs.get("learner_note") or "").strip()[:MAX_NOTE_LENGTH],
        "answer_length": length if length in ANSWER_LENGTHS else DEFAULT_ANSWER_LENGTH,
    }


def example_count(profile: dict[str, Any]) -> int:
    return _EXAMPLE_COUNT[profile.get("answer_length") or DEFAULT_ANSWER_LENGTH]


def _stretch_label(level: str) -> str:
    idx = LEVELS.index(level)
    return LEVELS[idx + 1] if idx + 1 < len(LEVELS) else "beyond N1"


def _profile_block(profile: dict[str, Any]) -> str:
    level = profile.get("level")
    if not level:
        return ""
    stretch = _stretch_label(level)
    note = profile.get("note") or ""
    note_line = f' Their own note: "{note}".' if note else ""
    return (
        "<learner_profile>\n"
        f"The learner studies Japanese at about JLPT {level}.{note_line}\n"
        "- Pitch the Japanese you write (`answer`, and each example's "
        "`japanese`) at the learner's level, with at most one or two words "
        f"or grammar points one step above it ({stretch}) — enough to "
        "stretch them without losing them. Text printed in the textbook is "
        "still copied verbatim whatever its level.\n"
        "- Name each such stretch item in `explanation` (for example: "
        f'"Stretch: 〜にもかかわらず ({stretch})") so the learner knows '
        "what is new.\n"
        "- For an `open` exercise, keep the first example at the learner's "
        "level; later examples may use the stretch.\n"
        "</learner_profile>\n"
    )


def render_exercise_completion_prompt(template: str, profile: dict[str, Any]) -> str:
    """Fill the completion prompt template for this learner."""
    length = profile.get("answer_length") or DEFAULT_ANSWER_LENGTH
    text = (
        template
        .replace("{example_count}", _NUMBER_WORDS[example_count(profile)])
        .replace("{question_length}", _QUESTION_LENGTH[length])
    )
    block = _profile_block(profile)
    return f"{text}\n{block}" if block else text
