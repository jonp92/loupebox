import importlib
import pkgutil

from app.core.config import settings
from app.inbound import sources as sources_pkg
from app.inbound.base import InboundSource

_sources: dict[str, InboundSource] = {}


def register_source(cls: type[InboundSource]) -> type[InboundSource]:
    if cls.key in _sources:
        raise ValueError(f"inbound source {cls.key!r} is already registered")
    _sources[cls.key] = cls()
    return cls


def get_source(key: str) -> InboundSource | None:
    return _sources.get(key)


def all_sources() -> list[InboundSource]:
    return list(_sources.values())


def load_sources() -> None:
    """Import every module under sources/ so its @register_source runs. Safe to call twice."""
    for mod in pkgutil.iter_modules(sources_pkg.__path__):
        importlib.import_module(f"{sources_pkg.__name__}.{mod.name}")


def inbound_enabled() -> bool:
    """True when customers' answers can actually reach us: an address to write to and a source reading it."""
    load_sources()
    return bool(settings.inbound_address) and any(s.is_configured() for s in _sources.values())
