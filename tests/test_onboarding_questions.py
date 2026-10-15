from onboarding import questions


def full_answers():
    return {
        "earliest_start": "2027-01-01", "permit_status": "Blue Card",
        "needs_sponsorship": "no", "authorized_countries": "Germany",
        "relocation": "Berlin", "remote_ok": "yes", "salary_expectation": "60.000 EUR",
        "notice_period": "3 months", "working_hours": "Vollzeit",
    }


class TestMissingFields:
    def test_complete_answers_miss_nothing(self):
        assert questions.missing_fields(full_answers()) == []

    def test_optional_fields_are_never_required(self):
        answers = full_answers()
        assert "contract_deadline" not in answers and "extra_skills" not in answers
        assert questions.missing_fields(answers) == []

    def test_a_cleared_answer_is_missing(self):
        answers = full_answers()
        answers["salary_expectation"] = "   "
        assert questions.missing_fields(answers) == ["salary_expectation"]


class TestQuestionSet:
    def test_every_uncovered_field_gets_its_fallback(self):
        model = [{"id": "q1", "field": "earliest_start", "text": "From when?", "type": "date",
                  "options": [], "suggested": "2027-01-01"}]
        qs = questions.complete_question_set(model, [])
        fields = [q["field"] for q in qs]
        assert fields[0] == "earliest_start"
        assert set(fields) == {f.key for f in questions.FIELDS}
        assert qs[0]["text"] == "From when?"  # the model's wording wins

    def test_a_field_asked_twice_is_shown_once(self):
        a = {"id": "a", "field": "role_kind:0", "text": "A", "type": "text", "options": [], "suggested": ""}
        b = dict(a, id="b", text="B")
        qs = questions.complete_question_set([a], [b])
        assert [q["text"] for q in qs if q["field"] == "role_kind:0"] == ["A"]

    def test_fallbacks_have_the_question_shape(self):
        (q,) = questions.fallback_questions(["working_hours"])
        assert set(q) == {"id", "field", "text", "type", "options", "suggested"}
        assert q["type"] == "choice" and q["options"]


def test_prompt_lists_every_field():
    text = questions.prompt_field_list()
    for spec in questions.FIELDS:
        assert spec.key in text


class TestReviewFixes:
    def test_catalogue_fields_keep_their_own_type_and_options(self):
        model = [{"id": "a", "field": "earliest_start", "text": "When?", "type": "text",
                  "options": [], "suggested": "April 2026"},
                 {"id": "b", "field": "needs_sponsorship", "text": "Visa?", "type": "choice",
                  "options": ["Yes, after graduation", "No"], "suggested": ""}]
        qs = {q["field"]: q for q in questions.complete_question_set(model, [])}
        assert qs["earliest_start"]["type"] == "date" and qs["earliest_start"]["text"] == "When?"
        assert qs["needs_sponsorship"]["type"] == "yes_no"
        assert qs["needs_sponsorship"]["options"] == []

    def test_an_unanswered_months_question_is_missing(self):
        form = [{"id": "m", "field": "role_months:0", "text": "How long?", "type": "text",
                 "options": [], "suggested": ""}]
        answers = dict(full_answers(), **{"role_months:0": ""})
        assert questions.missing_in_form(form, answers) == ["role_months:0"]
        answers["role_months:0"] = "14"
        assert questions.missing_in_form(form, answers) == []
