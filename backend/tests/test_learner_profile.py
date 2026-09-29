from __future__ import annotations

from app.config import EXERCISE_COMPLETION_PROMPT
from app.services import learner_profile, preferences


def _render(**profile):
    base = {"level": None, "note": "", "answer_length": "brief"}
    return learner_profile.render_exercise_completion_prompt(EXERCISE_COMPLETION_PROMPT, {**base, **profile})


def test_every_placeholder_is_filled():
    for length in learner_profile.ANSWER_LENGTHS:
        text = _render(answer_length=length, level="N3")
        assert "{example_count}" not in text and "{question_length}" not in text


def test_brief_asks_for_two_examples_and_a_short_answer():
    text = _render()
    assert "a list of two ALTERNATIVE COMPLETIONS" in text
    assert "Provide exactly two examples." in text
    assert "one short sentence (two if the question asks two things)" in text


def test_standard_and_detailed_keep_three_examples():
    assert "Provide exactly three examples." in _render(answer_length="standard")
    detailed = _render(answer_length="detailed")
    assert "Provide exactly three examples." in detailed
    assert "two to four sentences" in detailed


def test_no_level_means_no_profile_block():
    assert "<learner_profile>" not in _render()


def test_level_block_names_level_stretch_and_note():
    text = _render(level="N3", note="writing closer to N4")
    block = text[text.index("<learner_profile>"):]
    assert "JLPT N3" in block
    assert 'Their own note: "writing closer to N4".' in block
    assert "one step above it (N2)" in block
    assert "kanji above N3" in block
    assert text.rstrip().endswith("</learner_profile>")


def test_n1_stretches_beyond_n1():
    assert "one step above it (beyond N1)" in _render(level="N1")


def test_current_normalizes_saved_values(isolated_data_dir):
    preferences.save({"learner_level": "N9", "answer_length": "verbose", "learner_note": " x " + "y" * 300})
    profile = learner_profile.current()
    assert profile["level"] is None
    assert profile["answer_length"] == "brief"
    assert len(profile["note"]) == learner_profile.MAX_NOTE_LENGTH
    assert learner_profile.example_count(profile) == 2
