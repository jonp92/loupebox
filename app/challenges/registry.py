import importlib
import pkgutil

from app.challenges import verifiers as verifiers_pkg
from app.challenges.base import ChallengeVerifier

OFF = "off"

_verifiers: dict[str, ChallengeVerifier] = {}


def register_verifier(cls: type[ChallengeVerifier]) -> type[ChallengeVerifier]:
    if cls.key == OFF or cls.key in _verifiers:
        raise ValueError(f"challenge verifier {cls.key!r} is reserved or already registered")
    _verifiers[cls.key] = cls()
    return cls


def get_verifier(key: str) -> ChallengeVerifier | None:
    return _verifiers.get(key)


def all_verifiers() -> list[ChallengeVerifier]:
    return list(_verifiers.values())


def load_verifiers() -> None:
    """Import every module under verifiers/ so its @register_verifier runs. Safe to call twice."""
    for mod in pkgutil.iter_modules(verifiers_pkg.__path__):
        importlib.import_module(f"{verifiers_pkg.__name__}.{mod.name}")
