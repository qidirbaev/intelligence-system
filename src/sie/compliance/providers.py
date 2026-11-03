"""Model-provider allow-list (CG-6). Default deny: only listed providers may receive text.

A provider that processes data outside the approved region must carry `approved_ref`
(a pointer to the legal sign-off) or the file does not load.
"""

from collections.abc import Iterable
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, model_validator

Kind = Literal["llm", "embedding"]


class ProviderNotAllowed(PermissionError):
    """Raised when code tries to use a provider that is not on the allow-list."""


class Provider(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    kind: Kind
    location: str  # where processing happens, e.g. 'UZ', 'self-hosted', 'US'
    data_use_terms: str  # one line: retention and training use of submitted text
    cross_border: bool = False
    approved_ref: str | None = None  # legal sign-off reference

    @model_validator(mode="after")
    def _cross_border_needs_signoff(self) -> "Provider":
        if self.cross_border and not self.approved_ref:
            raise ValueError(
                f"provider '{self.name}' is cross-border and needs approved_ref (legal sign-off)"
            )
        return self


class ProviderRegistry:
    def __init__(self, providers: Iterable[Provider] = ()) -> None:
        self._by_key: dict[tuple[str, str], Provider] = {}
        for provider in providers:
            key = (provider.kind, provider.name)
            if key in self._by_key:
                raise ValueError(f"duplicate provider: {provider.kind}/{provider.name}")
            self._by_key[key] = provider

    @classmethod
    def from_file(cls, path: str | Path) -> "ProviderRegistry":
        data = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
        unknown = set(data) - {"providers"}
        if unknown:
            raise ValueError(f"unknown top-level keys in providers file: {sorted(unknown)}")
        return cls(Provider(**item) for item in data.get("providers", []))

    @classmethod
    def from_settings(cls, settings) -> "ProviderRegistry":
        """Empty (deny-all) registry when no providers file is configured."""
        if settings.providers_file is None:
            return cls()
        return cls.from_file(settings.providers_file)

    def get(self, name: str, kind: Kind) -> Provider | None:
        return self._by_key.get((kind, name))

    def is_allowed(self, name: str, kind: Kind) -> bool:
        return self.get(name, kind) is not None

    def require(self, name: str, kind: Kind) -> Provider:
        provider = self.get(name, kind)
        if provider is None:
            raise ProviderNotAllowed(f"{kind} provider '{name}' is not on the allow-list (CG-6)")
        return provider

    def names(self, kind: Kind) -> list[str]:
        return sorted(name for (k, name) in self._by_key if k == kind)
