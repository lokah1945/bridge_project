"""Provider registry — dynamic lookup + parsing of OpenAI-style model names.

A model name follows one of these formats:

    bridge/arena/<modality>/<model_id>   (modality ∈ {text, search, image, code})
    bridge/qwen/<model_id>
    bridge/deepseek/<model_id>

Any other format -> HTTP 400 (in the gateway) with a clear error message.
Unknown provider name -> HTTP 404.

Adding a new provider requires no changes here: drop ``providers/<name>.py``
containing a ``BaseProvider`` subclass; the next import will auto-register it.
"""

from __future__ import annotations

import importlib
import logging
import os
from typing import Any, Dict, List, Optional, Type

from providers.base import BaseProvider

logger = logging.getLogger("bridge.registry")

_ARENA_MODALITIES = {"text", "search", "image", "code"}


class ProviderRegistry:
    _registry: Dict[str, Type[BaseProvider]] = {}

    # ------------------------------------------------------------------ register

    @classmethod
    def register(cls, name: str) -> Any:
        """Decorator: ``@ProviderRegistry.register("arena")`` for a BaseProvider subclass."""

        def wrap(provider_cls: Type[BaseProvider]) -> Type[BaseProvider]:
            if not issubclass(provider_cls, BaseProvider):
                raise TypeError(f"{provider_cls} is not a BaseProvider subclass")
            if name in cls._registry:
                logger.debug("overriding existing provider %r with %s", name, provider_cls)
            cls._registry[name] = provider_cls
            return provider_cls

        return wrap

    # ------------------------------------------------------------------ lookup

    @classmethod
    def get_provider_class(cls, name: str) -> Optional[Type[BaseProvider]]:
        """Return the provider class for ``name`` or ``None``.

        Triggers a lazy import of ``providers.<name>`` which in turn triggers
        ``@ProviderRegistry.register`` decorators at module-load time.
        """
        if name in cls._registry:
            return cls._registry[name]
        try:
            importlib.import_module(f"providers.{name}")
        except ModuleNotFoundError:
            return None
        except Exception as exc:  # pragma: no cover - defensive
            logger.exception("import providers.%s failed: %s", name, exc)
            return None
        return cls._registry.get(name)

    @classmethod
    def known_providers(cls) -> List[str]:
        """Ensure every provider module under providers/ is imported + registered."""
        here = os.path.dirname(os.path.abspath(__file__))
        provs_dir = os.path.join(here, "providers")
        if not os.path.isdir(provs_dir):
            return list(cls._registry)
        for fname in os.listdir(provs_dir):
            if fname.endswith(".py") and not fname.startswith("_"):
                modname = fname[:-3]
                if modname == "base":
                    continue
                try:
                    importlib.import_module(f"providers.{modname}")
                except Exception as exc:  # pragma: no cover
                    logger.debug("skip import providers.%s: %s", modname, exc)
        return list(cls._registry)

    # ------------------------------------------------------------------ parse

    @classmethod
    def parse(cls, model: str) -> Dict[str, Any]:
        """Parse ``bridge/<provider>/[modality/]<model>``.

        Returns ``{"provider": ..., "model_id": ..., "modality": optional}``.
        Raises ``ValueError`` with a user-facing message on malformed input.
        """
        if not isinstance(model, str) or not model.startswith("bridge/"):
            raise ValueError(
                f"model {model!r} is not in bridge/ format. "
                "Use: bridge/<provider>/[modality/]<model>"
            )
        parts = model.split("/")
        # parts[0] = "bridge"
        if len(parts) < 3:
            raise ValueError(
                f"model {model!r} is incomplete. "
                "Use: bridge/<provider>/[modality/]<model>"
            )
        provider = parts[1]
        if not provider:
            raise ValueError(f"empty provider in {model!r}")

        if provider == "arena":
            # bridge/arena/<modality>/<model_id>
            if len(parts) != 4:
                raise ValueError(
                    f"arena model must be bridge/arena/<modality>/<model> "
                    f"(modality ∈ {_ARENA_MODALITIES}); got {model!r}"
                )
            modality, model_id = parts[2], parts[3]
            if modality not in _ARENA_MODALITIES:
                raise ValueError(
                    f"arena modality {modality!r} not in {_ARENA_MODALITIES}"
                )
            return {"provider": "arena", "modality": modality, "model_id": model_id}

        # bridge/<provider>/<model_id>
        if len(parts) != 3:
            raise ValueError(
                f"{provider} model must be bridge/{provider}/<model>; got {model!r}"
            )
        model_id = parts[2]
        if not model_id:
            raise ValueError(f"empty model id in {model!r}")
        return {"provider": provider, "model_id": model_id}

    @classmethod
    def get_provider_class_or_404(cls, name: str) -> Type[BaseProvider]:
        cls.known_providers()  # ensure all modules imported
        pc = cls.get_provider_class(name)
        if pc is None:
            raise KeyError(f"Provider {name!r} not found. Known: {sorted(cls._registry)}")
        return pc


# NOTE: discovery is triggered by client.py at startup, not at import time,
# to avoid circular imports between providers/*.py and registry.py.
# Each provider file does ``from registry import ProviderRegistry`` at the
# top — this works because registry has no providers.* import at module level.

