"""Communications package (Phase C)."""
from app.comms.base import CommsProvider, CommsResult
from app.comms.mock import MockCommsProvider

_default_provider = MockCommsProvider()


def get_comms_provider() -> CommsProvider:
    """Return configured comms provider (MockCommsProvider default)."""
    return _default_provider


__all__ = [
    "CommsProvider",
    "CommsResult",
    "MockCommsProvider",
    "get_comms_provider",
]
