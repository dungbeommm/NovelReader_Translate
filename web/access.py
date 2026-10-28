"""Compatibility alias: authentication moved to server.auth.access."""
import sys
from server.auth import access as _access

sys.modules[__name__] = _access
