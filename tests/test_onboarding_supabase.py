from unittest.mock import MagicMock

from db import supabase_utils


def test_upload_replaces_resume_pdf(monkeypatch):
    fake = MagicMock()
    monkeypatch.setattr(supabase_utils, "supabase", fake)
    assert supabase_utils.upload_base_resume_pdf(b"%PDF") is True
    fake.storage.from_.assert_called_with("resumes")
    kwargs = fake.storage.from_.return_value.upload.call_args.kwargs
    assert kwargs["path"] == "resume.pdf" and kwargs["file"] == b"%PDF"
    assert kwargs["file_options"]["upsert"] == "true"


def test_upload_failure_is_false(monkeypatch):
    fake = MagicMock()
    fake.storage.from_.return_value.upload.side_effect = RuntimeError("bucket missing")
    monkeypatch.setattr(supabase_utils, "supabase", fake)
    assert supabase_utils.upload_base_resume_pdf(b"%PDF") is False
    assert supabase_utils.upload_base_resume_pdf(b"") is False


def test_base_resume_exists_three_ways(monkeypatch):
    fake = MagicMock()
    monkeypatch.setattr(supabase_utils, "supabase", fake)
    query = fake.table.return_value.select.return_value.limit.return_value.execute
    query.return_value = MagicMock(data=[{"id": "x"}])
    assert supabase_utils.base_resume_exists() is True
    query.return_value = MagicMock(data=[])
    assert supabase_utils.base_resume_exists() is False
    query.side_effect = RuntimeError("unreachable")
    assert supabase_utils.base_resume_exists() is None
