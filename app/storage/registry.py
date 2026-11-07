import importlib
import pkgutil

from app.core.config import settings
from app.storage import backends as backends_pkg
from app.storage.base import Storage

_backends: dict[str, type[Storage]] = {}


def register_backend(cls: type[Storage]) -> type[Storage]:
    if cls.key in _backends:
        raise ValueError(f"storage backend {cls.key!r} is already registered")
    _backends[cls.key] = cls
    return cls


def load_backends() -> None:
    """Import every module under backends/ so its @register_backend runs. Safe to call twice."""
    for mod in pkgutil.iter_modules(backends_pkg.__path__):
        importlib.import_module(f"{backends_pkg.__name__}.{mod.name}")


def backend_names() -> list[str]:
    load_backends()
    return sorted(_backends)


def get_storage(name: str | None = None) -> Storage:
    """The named backend (default: the one `STORAGE_BACKEND` selects), built from the current settings, so
    keep construction cheap. Each attachment remembers its own backend, so old files stay reachable after the
    setting changes."""
    load_backends()
    name = name or settings.storage_backend
    try:
        return _backends[name]()
    except KeyError:
        raise RuntimeError(f"unknown storage backend {name!r}") from None
