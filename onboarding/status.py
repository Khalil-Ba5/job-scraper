"""What setup still needs, as a row of checks the Set up page draws.

Only things that can be read cheaply on every rerun: environment variables and
local files. The database check lives in the page, because it is a network call.

Streamlit-free, like review/apply_queue.py.
"""
import os
from dataclasses import dataclass
from typing import List, Mapping, Optional

import config
from onboarding import build

PROVIDER_KEYS = {
    "anthropic": "ANTHROPIC_API_KEY", "openai": "OPENAI_API_KEY", "gemini": "GEMINI_API_KEY",
    "google": "GEMINI_API_KEY", "groq": "GROQ_API_KEY", "deepseek": "DEEPSEEK_API_KEY",
    "mistral": "MISTRAL_API_KEY", "openrouter": "OPENROUTER_API_KEY",
}


@dataclass(frozen=True)
class Check:
    label: str
    ok: bool
    fix: str


def _set(env: Mapping[str, str], name: str) -> bool:
    return bool(str(env.get(name) or "").strip())


def provider_key_name(model: str) -> Optional[str]:
    provider = model.split("/")[0].lower() if "/" in model else model.lower()
    return PROVIDER_KEYS.get(provider)


def env_checks(env: Mapping[str, str], model: str) -> List[Check]:
    supabase_ok = _set(env, "SUPABASE_URL") and _set(env, "SUPABASE_SERVICE_ROLE_KEY")
    key_name = provider_key_name(model)
    key_ok = (key_name is not None and _set(env, key_name)) or _set(env, "LLM_API_KEY")
    key_fix = (f"Set {key_name} in .env" if key_name
               else f"Set the API key for '{model}' in .env (see docs/configuration.md)")
    return [
        Check("Supabase settings", supabase_ok,
              "Set SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY in .env, then restart the app."),
        Check("LLM key", key_ok, key_fix + ", then restart the app."),
    ]


def profile_present(path: Optional[str] = None, env: Optional[Mapping[str, str]] = None) -> bool:
    """A profile the scorer will accept: the CI secret, or a valid local file."""
    env = os.environ if env is None else env
    if _set(env, "CANDIDATE_PROFILE_JSON"):
        return True
    profile = build.read_json(path or config.CANDIDATE_PROFILE_PATH)
    if profile is None:
        return False
    try:
        build.validate_profile(profile)
        return True
    except ValueError:
        return False
