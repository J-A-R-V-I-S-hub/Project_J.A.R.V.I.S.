from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from importlib.metadata import entry_points
from typing import Any

from .config import Settings

LOGGER = logging.getLogger(__name__)


@dataclass(slots=True)
class PluginContext:
    settings: Settings
    chat_id: int
    artifacts: Any = None


@dataclass(slots=True)
class Plugin:
    """A bundle of extra tools and instructions contributed by a plugin."""

    name: str
    tools: list[object] = field(default_factory=list)
    instructions: list[str] = field(default_factory=list)


PluginFactory = Callable[[PluginContext], Plugin]


class PluginRegistry:
    """Small plugin registry.

    Third-party packages can expose a factory via the ``jarvis.plugins``
    entry point group:

        [project.entry-points."jarvis.plugins"]
        my_plugin = "my_package.jarvis_plugin:build"

    where ``build(context: PluginContext) -> Plugin``.
    """

    def __init__(self) -> None:
        self._factories: dict[str, PluginFactory] = {}

    def register(self, name: str, factory: PluginFactory) -> None:
        self._factories[name] = factory

    def names(self) -> list[str]:
        return sorted(self._factories)

    def load_entry_points(self, group: str = "jarvis.plugins") -> list[str]:
        loaded: list[str] = []
        try:
            discovered = entry_points(group=group)
        except TypeError:  # pragma: no cover - old importlib.metadata API
            discovered = entry_points().get(group, [])  # type: ignore[attr-defined]
        for entry_point in discovered:
            try:
                factory = entry_point.load()
            except Exception:
                LOGGER.warning("Could not load plugin %s", entry_point.name, exc_info=True)
                continue
            if callable(factory):
                self.register(entry_point.name, factory)
                loaded.append(entry_point.name)
        return loaded

    def build(self, context: PluginContext) -> tuple[list[object], list[str]]:
        tools: list[object] = []
        instructions: list[str] = []
        for name, factory in self._factories.items():
            try:
                plugin = factory(context)
            except Exception:
                LOGGER.warning("Plugin %s failed to build", name, exc_info=True)
                continue
            if not isinstance(plugin, Plugin):
                LOGGER.warning("Plugin %s returned an invalid object", name)
                continue
            tools.extend(plugin.tools)
            instructions.extend(plugin.instructions)
        return tools, instructions
