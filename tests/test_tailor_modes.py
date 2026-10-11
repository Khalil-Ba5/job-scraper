"""Writing only the CV, or only the cover letter.

Every model call is stubbed. What is under test is that the choice reaches each
stage: the writer is held to a schema with only the chosen document, a revision
keeps to it, the judge is told not to object to the absent one, and saving one
document leaves the other from an earlier run alone.
"""

import json

import pytest

from tailor import judge, loop, store, verify, writer
from tailor.documents import (Application, CoverLetter, Line, TailoredCV, all_lines,
                              mode_of, response_model)

JOB = {"job_id": "j1", "job_title": "ML Engineer", "company": "ACME",
       "description": "Airflow, Databricks, production models."}

CV = TailoredCV(headline="ML Engineer", summary=Line(text="Built the pipeline.", fact_ids=["f1"]))
LETTER = CoverLetter(subject="ML Engineer", greeting="Hallo,",
                     paragraphs=[Line(text="I built the pipeline.", fact_ids=["f1"])],
                     closing="Beste Gruesse")


class _Base:
    """Just enough fact base for the writer's system prompt and the verifier."""

    def render(self):
        return "f1: built the pipeline"

    def ids(self):
        return {"f1"}

    def by_id(self, fid):
        return None


@pytest.fixture
def llm(monkeypatch):
    """Capture what the writer asks for and answer with the schema it named."""
    from scoring import llm_client

    calls = []

    def generate_content(prompt, response_format=None, **_k):
        calls.append({"prompt": prompt, "schema": response_format})
        fields = response_format.model_fields
        reply = {}
        if "cv" in fields:
            reply["cv"] = CV.model_dump()
        if "cover_letter" in fields:
            reply["cover_letter"] = LETTER.model_dump()
        return json.dumps(reply)

    monkeypatch.setattr(llm_client.primary_client, "generate_content", generate_content)
    monkeypatch.setattr(writer, "_availability_note", lambda: "today")
    return calls


class TestWriter:
    def test_a_letter_only_draft_has_no_cv(self, llm):
        app = writer.write(JOB, _Base(), {}, mode="letter")
        assert app.cv is None and app.cover_letter is not None
        assert set(llm[0]["schema"].model_fields) == {"cover_letter"}
        assert "Write only the Anschreiben" in llm[0]["prompt"]

    def test_a_cv_only_draft_has_no_letter(self, llm):
        app = writer.write(JOB, _Base(), {}, mode="cv")
        assert app.cover_letter is None and app.cv is not None
        assert set(llm[0]["schema"].model_fields) == {"cv"}

    def test_both_is_still_the_default(self, llm):
        app = writer.write(JOB, _Base(), {})
        assert mode_of(app) == "both"

    def test_a_revision_keeps_to_the_documents_it_was_given(self, llm):
        """A letter-only run must not grow a CV on round two."""
        revised = writer.revise(JOB, _Base(), {}, Application(cover_letter=LETTER), ["objection"])
        assert revised.cv is None
        assert set(llm[0]["schema"].model_fields) == {"cover_letter"}


def test_the_loop_passes_the_choice_to_the_first_draft(monkeypatch):
    seen = {}

    def write(job, base, personal, mode="both"):
        seen["mode"] = mode
        return Application(cv=CV)

    monkeypatch.setattr(loop.writer, "write", write)
    monkeypatch.setattr(loop.verify, "verify", lambda *_a, **_k: verify.VerifyResult())
    monkeypatch.setattr(loop.judge_mod, "review", lambda job, app: None)
    loop.run(JOB, base=object(), personal={}, max_rounds=1, mode="cv")
    assert seen["mode"] == "cv"


def test_the_judge_is_told_not_to_ask_for_the_missing_letter(monkeypatch):
    from scoring import llm_client

    prompts = []
    monkeypatch.setattr(judge, "_availability_note", lambda: "today")
    monkeypatch.setattr(llm_client.primary_client, "generate_content",
                        lambda prompt, **_k: prompts.append(prompt) or "{}")
    judge.review(JOB, Application(cv=CV), attempts=1)
    assert "### CV" in prompts[0]
    assert "### Cover letter" not in prompts[0]
    assert "Do not object that there is no cover letter" in prompts[0]


def test_the_verifier_walks_only_what_exists():
    app = Application(cover_letter=LETTER)
    assert [line.text for line in all_lines(app)] == ["I built the pipeline."]
    assert verify.verify(app, _Base()).ok


class TestSavingOneDocument:
    def _result(self, app, score_after=None):
        return loop.Result(application=app, score_after=score_after,
                           score_before=40 if score_after else None)

    def test_writing_the_letter_keeps_the_earlier_cv_and_its_score(self, monkeypatch, tmp_path):
        monkeypatch.setattr(store.settings, "OUTPUT_DIR", str(tmp_path))
        store.save(JOB, self._result(Application(cv=CV), score_after=55))
        store.save(JOB, self._result(Application(cover_letter=LETTER)))

        saved = store.load("j1")
        assert "Built the pipeline." in saved["cv_text"]
        assert "I built the pipeline." in saved["cover_letter_text"]
        assert saved["score_after"] == 55
        # The draft a further round would continue is only what this run wrote.
        assert saved["application"]["cv"] is None

    def test_a_fresh_cv_replaces_the_old_one(self, monkeypatch, tmp_path):
        monkeypatch.setattr(store.settings, "OUTPUT_DIR", str(tmp_path))
        store.save(JOB, self._result(Application(cv=CV)))
        newer = CV.model_copy(update={"headline": "Senior ML Engineer"})
        store.save(JOB, self._result(Application(cv=newer)))
        assert store.load("j1")["cv_text"].startswith("Senior ML Engineer")


@pytest.mark.parametrize("mode, fields", [("both", {"cv", "cover_letter"}),
                                          ("cv", {"cv"}), ("letter", {"cover_letter"})])
def test_each_choice_has_a_strict_schema(mode, fields):
    """Required fields, so a model cannot quietly drop a document it was asked for."""
    model = response_model(mode)
    assert set(model.model_fields) == fields
    assert all(f.is_required() for f in model.model_fields.values())
