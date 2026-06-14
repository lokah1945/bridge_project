"""Provider implementations for bridge-client.

Importing this package triggers the @ProviderRegistry.register decorators
on each provider class — no manual list maintained.
"""

from .base import BaseProvider
from . import arena as _arena_mod  # noqa: F401
from . import qwen as _qwen_mod  # noqa: F401
from . import deepseek as _ds_mod  # noqa: F401

__all__ = ["BaseProvider"]
