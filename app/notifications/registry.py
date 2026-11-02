import importlib
import pkgutil

from app.notifications import providers as providers_pkg
from app.notifications.base import NotificationProvider

_providers: dict[str, NotificationProvider] = {}


def register_provider(cls: type[NotificationProvider]) -> type[NotificationProvider]:
    if cls.key in _providers:
        raise ValueError(f"notification provider {cls.key!r} is already registered")
    _providers[cls.key] = cls()
    return cls


def get_provider(key: str) -> NotificationProvider | None:
    return _providers.get(key)


def all_providers() -> list[NotificationProvider]:
    return list(_providers.values())


def load_providers() -> None:
    """Import every module under providers/ so its @register_provider runs. Safe to call twice."""
    for mod in pkgutil.iter_modules(providers_pkg.__path__):
        importlib.import_module(f"{providers_pkg.__name__}.{mod.name}")
