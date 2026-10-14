"""Every prompt that can mention a date is told what today is.

The failure this guards against is specific and was live: a five-month wait to
the earliest start date reported to the user as seventeen months. The arithmetic
was never the problem — `availability_note()` has always computed it correctly —
the problem was prompts that were never shown the figure, most damagingly the
"why me" pitch, which is sent to employers in her own voice.
"""

import pytest

from scoring import availability


class TestTheNote:
    def test_it_states_the_gap_already_worked_out(self):
        """A model given only today's date still answers 'rund 18 Monate'."""
        note = availability.note()
        assert "days from today" in note
        assert "months" in note

    def test_it_forbids_the_model_doing_its_own_date_maths(self):
        """The half that actually stops '17 months' — and it must survive the fallback."""
        for text in (availability.note(), _fallback_note()):
            assert "NEVER state how many months" in text or \
                   "Never state how many months" in text

    def test_a_missing_profile_still_yields_a_usable_block(self, monkeypatch):
        """The tailoring package must work for someone with no candidate profile."""
        assert "Today's date is" in _fallback_note()


def _fallback_note():
    import sys
    from unittest.mock import patch

    with patch.dict(sys.modules, {"scoring.score_jobs": None}):
        return availability.note()


class TestEveryPromptSite:
    """Each of these builds a prompt that can state or imply a date."""

    def test_the_scorer_carries_it(self, monkeypatch):
        from scoring import score_jobs

        captured = {}

        def fake(prompt, system_prompt, **k):
            captured["s"] = system_prompt
            raise RuntimeError("stop")

        monkeypatch.setattr(score_jobs.primary_client, "generate_content", fake)
        score_jobs.get_resume_score_from_ai(
            "resume", {"job_id": "j1", "job_title": "x", "company": "y", "description": "z"})
        assert "Today's date is" in captured["s"]

    @pytest.mark.parametrize("module", ["tailor.judge", "tailor.writer",
                                        "tailor.interview", "tailor.facts",
                                        "resume.custom_resume_generator"])
    def test_the_module_has_a_date_helper_wired_to_the_shared_one(self, module):
        """Every prompt-building module reaches the same block, not its own copy.

        Local copies were the original bug: two modules had a fallback that
        returned a bare date and silently dropped the no-durations rule.
        """
        import importlib
        import inspect

        mod = importlib.import_module(module)
        helper = getattr(mod, "_today", None) or getattr(mod, "_availability_note", None)
        assert helper is not None, f"{module} builds prompts with no date helper"
        assert "scoring.availability" in inspect.getsource(helper), \
            f"{module} does not use the shared availability note"
