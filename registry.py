
import importlib
from typing import Dict, Type
from providers.base import BaseProvider

class ProviderRegistry:
    def __init__(self):
        self._providers: Dict[str, Type[BaseProvider]] = {}

    def register(self, name: str, provider_class: Type[BaseProvider]):
        self._providers[name.lower()] = provider_class

    def get_provider_class(self, provider_name: str):
        name = provider_name.lower()
        if name not in self._providers:
            # Attempt dynamic import
            try:
                module = importlib.import_module(f"providers.{name}")
                # Look for a class that inherits from BaseProvider
                for attr_name in dir(module):
                    attr = getattr(module, attr_name)
                    if isinstance(attr, type) and issubclass(attr, BaseProvider) and attr is not BaseProvider:
                        self.register(name, attr)
                        return attr
            except ImportError:
                return None
        return self._providers.get(name)

registry = ProviderRegistry()
