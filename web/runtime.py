"""Compatibility alias: web.runtime and core.runtime share one module object."""
import sys
from core import runtime as _runtime

sys.modules[__name__] = _runtime
