from pathlib import Path

import pytest
from pydantic import ValidationError

from sie.compliance.providers import Provider, ProviderNotAllowed, ProviderRegistry
from sie.config import Settings

EXAMPLE = Path(__file__).parent.parent / "config" / "providers.example.yaml"


def provider(**kwargs) -> Provider:
    base = dict(name="p", kind="llm", location="self-hosted", data_use_terms="none")
    return Provider(**{**base, **kwargs})


def test_empty_registry_denies_everything():
    registry = ProviderRegistry()
    assert not registry.is_allowed("anything", "llm")
    with pytest.raises(ProviderNotAllowed):
        registry.require("anything", "llm")


def test_allowed_provider_and_kind_matters():
    registry = ProviderRegistry([provider(name="a", kind="llm")])
    assert registry.is_allowed("a", "llm")
    assert not registry.is_allowed("a", "embedding")  # same name, other kind
    assert registry.require("a", "llm").location == "self-hosted"


def test_cross_border_requires_signoff():
    with pytest.raises(ValidationError):
        provider(cross_border=True)
    assert provider(cross_border=True, approved_ref="legal-2026-12").approved_ref


def test_unknown_fields_rejected():
    with pytest.raises(ValidationError):
        Provider(name="p", kind="llm", location="x", data_use_terms="y", typo_field=1)


def test_duplicate_provider_rejected():
    with pytest.raises(ValueError, match="duplicate"):
        ProviderRegistry([provider(name="a"), provider(name="a")])


def test_example_file_loads():
    registry = ProviderRegistry.from_file(EXAMPLE)
    assert registry.names("embedding") == ["local-embedder"]
    assert registry.names("llm") == ["fake-llm"]


def test_from_settings_without_file_is_deny_all():
    registry = ProviderRegistry.from_settings(Settings(_env_file=None))
    assert registry.names("llm") == [] and registry.names("embedding") == []


def test_from_settings_with_file():
    registry = ProviderRegistry.from_settings(Settings(_env_file=None, providers_file=EXAMPLE))
    assert registry.is_allowed("local-embedder", "embedding")


def test_bad_top_level_key_rejected(tmp_path):
    bad = tmp_path / "p.yaml"
    bad.write_text("provider: []\n")
    with pytest.raises(ValueError, match="unknown top-level"):
        ProviderRegistry.from_file(bad)
