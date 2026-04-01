"""Thread-safe in-memory tool registry for MCP tools."""

from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import Any, Callable


@dataclass
class ToolDefinition:
    """Definition of a single MCP tool.

    Attributes:
        name: Unique tool name (e.g. "device_list").
        func: The callable tool function.
        description: Human-readable description for the MCP manifest.
        input_schema: JSON Schema dict for tool input parameters.
        tier: "core" for always-available tools, "app" for registered third-party tools.
        app_label: Django app label for app-tier tools (e.g. "netnam_cms_core").
        scope: Dot-separated scope string (e.g. "netnam_cms_core.juniper"). None for core tools.
    """

    name: str
    func: Callable
    description: str
    input_schema: dict[str, Any]
    tier: str = "core"
    app_label: str | None = None
    scope: str | None = None


class MCPToolRegistry:
    """Thread-safe singleton registry for MCP tools.

    Uses double-checked locking with threading.Lock to safely support
    concurrent reads (every MCP request) and writes (third-party app
    registration at startup).
    """

    _instance: MCPToolRegistry | None = None
    _lock = threading.Lock()
    _tools: dict[str, ToolDefinition] = {}

    @classmethod
    def get_instance(cls) -> MCPToolRegistry:
        """Return the singleton registry instance (creating it on first call)."""
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    def register(self, tool: ToolDefinition) -> None:
        """Register a tool. Raises ValueError if name is already registered."""
        with self._lock:
            if tool.name in self._tools:
                raise ValueError(f"Tool already registered: {tool.name}")
            self._tools[tool.name] = tool

    def get_all(self) -> list[ToolDefinition]:
        """Return all registered tools."""
        return list(self._tools.values())

    def get_core_tools(self) -> list[ToolDefinition]:
        """Return all core-tier tools."""
        return [t for t in self._tools.values() if t.tier == "core"]

    def get_by_scope(self, scope: str) -> list[ToolDefinition]:
        """Return all tools matching an exact scope or any child scope.

        Args:
            scope: The scope to match. "core" returns all core tools.
                "netnam_cms_core" returns all tools under that app (any sub-scope).
                "netnam_cms_core.juniper" returns tools with that exact scope.
        """
        if scope == "core":
            return self.get_core_tools()
        return [
            t for t in self._tools.values()
            if t.scope == scope
            or (t.scope is not None and t.scope.startswith(f"{scope}."))
        ]

    def fuzzy_search(self, term: str) -> list[ToolDefinition]:
        """Fuzzy match tools by name or description (case-insensitive).

        Args:
            term: Search term to match in tool name or description.

        Returns:
            All tools whose name or description contains the term.
        """
        term_lower = term.lower()
        return [
            t for t in self._tools.values()
            if term_lower in t.name.lower() or term_lower in t.description.lower()
        ]
