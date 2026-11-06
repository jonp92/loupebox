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


def get_storage() -> Storage:
    """The backend `STORAGE_BACKEND` names, built from the current settings (so keep construction cheap)."""
    load_backends()
    try:
        return _backends[settings.storage_backend]()
    except KeyError:
        raise RuntimeError(f"unknown STORAGE_BACKEND {settings.storage_backend!r}") from None
