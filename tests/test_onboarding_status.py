import json

from onboarding import status
from tests.onboarding_samples import ANSWERS, LEDGER, make_draft

SUPA = {"SUPABASE_URL": "https://x.supabase.co", "SUPABASE_SERVICE_ROLE_KEY": "k"}


class TestEnvChecks:
    def test_all_set(self):
        checks = status.env_checks(dict(SUPA, ANTHROPIC_API_KEY="sk-ant"), "anthropic/claude-haiku-4-5")
        assert [c.ok for c in checks] == [True, True]

    def test_missing_supabase_names_the_variables(self):
        supa, key = status.env_checks({"ANTHROPIC_API_KEY": "sk"}, "anthropic/x")
        assert not supa.ok and "SUPABASE_URL" in supa.fix
        assert key.ok

    def test_the_key_must_match_the_provider(self):
        _, key = status.env_checks(dict(SUPA, ANTHROPIC_API_KEY="sk"), "openai/gpt-4o-mini")
        assert not key.ok and "OPENAI_API_KEY" in key.fix

    def test_generic_llm_api_key_counts(self):
        _, key = status.env_checks(dict(SUPA, LLM_API_KEY="x"), "groq/llama")
        assert key.ok

    def test_blank_values_do_not_count(self):
        supa, key = status.env_checks({"SUPABASE_URL": " ", "SUPABASE_SERVICE_ROLE_KEY": "k",
                                       "ANTHROPIC_API_KEY": ""}, "anthropic/x")
        assert not supa.ok and not key.ok


class TestProfilePresent:
    def test_a_valid_file(self, tmp_path):
        from onboarding import build
        path = tmp_path / "p.json"
        path.write_text(json.dumps(build.build_profile(make_draft(), ANSWERS, LEDGER)), encoding="utf-8")
        assert status.profile_present(str(path), env={})

    def test_missing_or_broken_file(self, tmp_path):
        assert not status.profile_present(str(tmp_path / "none.json"), env={})
        broken = tmp_path / "b.json"
        broken.write_text('{"short_profile": "x"}', encoding="utf-8")
        assert not status.profile_present(str(broken), env={})

    def test_the_ci_secret_counts(self, tmp_path):
        assert status.profile_present(str(tmp_path / "none.json"),
                                      env={"CANDIDATE_PROFILE_JSON": "{...}"})
