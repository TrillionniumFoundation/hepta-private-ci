"""Read-only inventory of an explicitly enrolled isolated Debian rootfs."""
from .parsers import DiscoveryError
from .reader import DiscoveryCandidate, DiscoveryScope, discover

__all__ = ["DiscoveryCandidate", "DiscoveryError", "DiscoveryScope", "discover"]
