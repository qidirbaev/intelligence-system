import pytest
from pydantic import ValidationError

from sie.config import DEV_DATABASE_URL, Settings, clear_settings_cache, get_settings


def make(**kwargs) -> Settings:
    return Settings(_env_file=None, **kwargs)


def test_defaults():
    s = make()
    assert s.env == "dev"
    assert s.database_url == DEV_DATABASE_URL
    assert s.tenant_id == "default"
    assert s.log_level == "INFO" and s.log_json is True
    assert s.data_region == "UZ"
    assert s.providers_file is None


def test_env_overrides(monkeypatch, tmp_path):
    monkeypatch.setenv("SIE_ENV", "test")
    monkeypatch.setenv("DATABASE_URL", "sqlite+pysqlite:///:memory:")
    monkeypatch.setenv("SIE_LOG_LEVEL", "debug")
    monkeypatch.setenv("SIE_PROVIDERS_FILE", str(tmp_path / "p.yaml"))
    monkeypatch.setenv("TELEGRAM_API_ID", "12345")
    s = make()
    assert s.env == "test"
    assert s.database_url.startswith("sqlite")
    assert s.log_level == "DEBUG"
    assert s.providers_file == tmp_path / "p.yaml"
    assert s.telegram_api_id == 12345


def test_prefixed_database_url_also_works(monkeypatch):
    monkeypatch.setenv("SIE_DATABASE_URL", "sqlite+pysqlite:///:memory:")
    assert make().database_url.startswith("sqlite")


@pytest.mark.parametrize("url", ["mysql://x", "redis://localhost", ""])
def test_unsupported_database_rejected(url):
    with pytest.raises(ValidationError):
        make(database_url=url)


def test_bad_log_level_rejected():
    with pytest.raises(ValidationError):
        make(log_level="LOUD")


def test_prod_requires_secrets():
    with pytest.raises(ValidationError) as info:
        make(env="prod")
    assert "hmac_secret" in str(info.value) and "session_encryption_key" in str(info.value)
    ok = make(env="prod", hmac_secret="a" * 32, session_encryption_key="b" * 32)
    assert ok.env == "prod"


def test_secrets_never_appear_in_repr_or_dump():
    s = make(hmac_secret="super-secret-value", telegram_api_hash="hash-value")
    text = repr(s) + str(s) + s.model_dump_json()
    assert "super-secret-value" not in text
    assert "hash-value" not in text
    assert s.hmac_secret.get_secret_value() == "super-secret-value"


def test_get_settings_is_cached_until_cleared(monkeypatch):
    monkeypatch.setenv("SIE_TENANT_ID", "one")
    assert get_settings().tenant_id == "one"
    monkeypatch.setenv("SIE_TENANT_ID", "two")
    assert get_settings().tenant_id == "one"  # cached
    clear_settings_cache()
    assert get_settings().tenant_id == "two"
