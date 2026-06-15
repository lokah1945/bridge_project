"""Provider registry for dynamic provider dispatch.

Providers are loaded from the `providers` package. A provider class must be
a concrete subclass of `BaseProvider`. If multiple classes exist in a module,
the one whose name matches the provider name (case-insensitive) is preferred.
"""
import importlib
from typing import Dict, Optional, Type

from providers.base import BaseProvider


class ProviderRegistry:
    def __init__(self):
        self._providers: Dict[str, Type[BaseProvider]] = {}

    def register(self, name: str, provider_class: Type[BaseProvider]) -> None:
        """Explicitly register a provider class."""
        if not issubclass(provider_class, BaseProvider) or provider_class is BaseProvider:
            raise ValueError(f"Cannot register non-provider class: {provider_class}")
        self._providers[name.lower()] = provider_class

    def get_provider_class(self, provider_name: str) -> Optional[Type[BaseProvider]]:
        """Return the registered provider class, loading it dynamically if needed."""
        name = provider_name.lower()
        if name in self._providers:
            return self._providers[name]

        # Dynamic import without side-effect of registration until we are sure.
        try:
            module = importlib.import_module(f"providers.{name}")
        except ImportError:
            return None

        candidates: list[Type[BaseProvider]] = []
        for attr_name in dir(module):
            attr = getattr(module, attr_name)
            if isinstance(attr, type) and issubclass(attr, BaseProvider) and attr is not BaseProvider:
                candidates.append(attr)

        if not candidates:
            return None

        # Prefer the class whose name matches the provider name (e.g. ArenaProvider).
        chosen: Optional[Type[BaseProvider]] = None
        lower_name = name.lower()
        for cls in candidates:
            if lower_name in cls.__name__.lower():
                chosen = cls
                break
        if chosen is None:
            chosen = candidates[0]

        self._providers[name] = chosen
        return chosen


registry = ProviderRegistry()
