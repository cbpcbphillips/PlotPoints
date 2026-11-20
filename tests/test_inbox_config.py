"""Where the S3 inbox gets its credentials: the environment first, a local .env as a fallback."""

import pytest

from api.inbox import Inbox


@pytest.fixture
def captured(monkeypatch):
    """Replace boto3.client so no AWS call is made, and record how it was built."""
    calls = []
    monkeypatch.setattr("boto3.client", lambda *a, **kw: calls.append(kw) or object())
    for name in (
        "INBOX_AWS_ACCESS_KEY_ID",
        "INBOX_AWS_SECRET_ACCESS_KEY",
        "AWS_S3_BUCKET",
        "AWS_REGION",
    ):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("PLOTPOINTS_INBOX", "s3")
    return calls


def write_env(tmp_path, monkeypatch, text):
    (tmp_path / ".env").write_text(text, encoding="utf-8")
    monkeypatch.chdir(tmp_path)


def test_a_local_env_file_is_enough_in_development(tmp_path, monkeypatch, captured):
    write_env(
        tmp_path,
        monkeypatch,
        "INBOX_AWS_ACCESS_KEY_ID=idfromfile\nINBOX_AWS_SECRET_ACCESS_KEY=secretfromfile\n"
        "AWS_S3_BUCKET=bucketfromfile\nAWS_REGION=eu-west-2\n",
    )
    inbox = Inbox()
    assert captured[0]["aws_access_key_id"] == "idfromfile"
    assert captured[0]["aws_secret_access_key"] == "secretfromfile"
    assert captured[0]["region_name"] == "eu-west-2"
    assert inbox._bucket == "bucketfromfile"


def test_the_environment_wins_over_the_file(tmp_path, monkeypatch, captured):
    write_env(
        tmp_path,
        monkeypatch,
        "INBOX_AWS_ACCESS_KEY_ID=fromfile\nINBOX_AWS_SECRET_ACCESS_KEY=fromfile\n"
        "AWS_S3_BUCKET=filebucket\n",
    )
    monkeypatch.setenv("INBOX_AWS_ACCESS_KEY_ID", "fromenv")
    monkeypatch.setenv("AWS_S3_BUCKET", "envbucket")
    inbox = Inbox()
    assert captured[0]["aws_access_key_id"] == "fromenv"
    assert inbox._bucket == "envbucket"


def test_the_pipeline_uploaders_keys_are_never_used_by_the_api(tmp_path, monkeypatch, captured):
    write_env(
        tmp_path,
        monkeypatch,
        "AWS_ACCESS_KEY_ID=uploaderid\nAWS_SECRET_ACCESS_KEY=uploadersecret\nAWS_S3_BUCKET=b\n",
    )
    with pytest.raises(RuntimeError, match="INBOX_AWS_ACCESS_KEY_ID"):
        Inbox()
    assert captured == []  # no client was built from the uploader's credentials


def test_missing_settings_say_which_ones(tmp_path, monkeypatch, captured):
    write_env(tmp_path, monkeypatch, "AWS_S3_BUCKET=b\n")
    with pytest.raises(RuntimeError) as err:
        Inbox()
    assert "INBOX_AWS_ACCESS_KEY_ID" in str(err.value)
    assert "INBOX_AWS_SECRET_ACCESS_KEY" in str(err.value)
    assert "AWS_S3_BUCKET" not in str(err.value)


def test_local_mode_needs_none_of_it(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("PLOTPOINTS_INBOX", "local")
    assert Inbox().mode == "local"
