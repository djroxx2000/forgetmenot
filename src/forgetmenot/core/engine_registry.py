import importlib
import logging
import pkgutil

import forgetmenot.engines as engines_pkg
from forgetmenot.engines.base import SourceEngine

logger = logging.getLogger(__name__)


class EngineRegistry:
    """Discovers and manages source engines.

    Auto-discovers SourceEngine subclasses from the forgetmenot.engines package.
    """

    def __init__(self) -> None:
        self._engines: dict[str, SourceEngine] = {}

    def discover(self) -> None:
        """Scan forgetmenot.engines for SourceEngine subclasses and register them."""
        for importer, modname, ispkg in pkgutil.iter_modules(engines_pkg.__path__, engines_pkg.__name__ + "."):
            if modname.endswith(".base"):
                continue
            try:
                module = importlib.import_module(modname)
            except Exception:
                logger.warning("Failed to import engine module %s", modname, exc_info=True)
                continue

            for attr_name in dir(module):
                attr = getattr(module, attr_name)
                if (
                    isinstance(attr, type)
                    and issubclass(attr, SourceEngine)
                    and attr is not SourceEngine
                    and hasattr(attr, "engine_type")
                    and isinstance(getattr(attr, "engine_type", None), str)
                ):
                    self.register(attr())

    def register(self, engine: SourceEngine) -> None:
        if engine.engine_type in self._engines:
            logger.warning("Engine type '%s' already registered, overwriting", engine.engine_type)
        self._engines[engine.engine_type] = engine
        logger.info("Registered engine: %s", engine.engine_type)

    def get(self, engine_type: str) -> SourceEngine:
        if engine_type not in self._engines:
            raise KeyError(f"No engine registered for type '{engine_type}'. Available: {list(self._engines.keys())}")
        return self._engines[engine_type]

    def list_engines(self) -> list[str]:
        return list(self._engines.keys())

    @property
    def engines(self) -> dict[str, SourceEngine]:
        return dict(self._engines)
