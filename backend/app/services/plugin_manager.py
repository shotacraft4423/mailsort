"""Plugin loader. A plugin is a directory under `plugins/` containing a
`plugin.json` manifest and a Python module exposing a `Plugin` subclass.
Deliberately has zero import-time dependency on any other domain module
(mail/company/deal) so plugins stay swappable — the app calls plugin hooks
with plain dicts, never ORM objects, per DESIGN.md section 7's "疎結合"
requirement.

Hot-reload (file-watch triggered re-import) is a Phase 2 item; this module
implements a manual `reload_plugins()` you can call from an API route or a
file-watcher, which is the seam a watchdog-based implementation would hook
into later.
"""
from __future__ import annotations

import importlib.util
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol


class Plugin(Protocol):
    def on_message_classified(self, message: dict[str, Any], classification: dict[str, Any]) -> None: ...
    def on_meeting_extracted(self, meeting: dict[str, Any]) -> None: ...


@dataclass
class PluginManifest:
    key: str
    name: str
    version: str
    entrypoint: str  # "module:ClassName"
    path: Path


@dataclass
class PluginRegistry:
    manifests: dict[str, PluginManifest] = field(default_factory=dict)
    instances: dict[str, Plugin] = field(default_factory=dict)


_registry = PluginRegistry()


def discover(plugins_dir: Path) -> list[PluginManifest]:
    manifests = []
    if not plugins_dir.exists():
        return manifests
    for manifest_path in plugins_dir.glob("*/plugin.json"):
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifests.append(
            PluginManifest(
                key=data["key"],
                name=data.get("name", data["key"]),
                version=data.get("version", "0.0.0"),
                entrypoint=data["entrypoint"],
                path=manifest_path.parent,
            )
        )
    return manifests


def _load_entrypoint(manifest: PluginManifest) -> Plugin:
    module_name, class_name = manifest.entrypoint.split(":")
    module_path = manifest.path / f"{module_name}.py"
    spec = importlib.util.spec_from_file_location(f"mailsort_plugin_{manifest.key}", module_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load plugin module at {module_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    plugin_class = getattr(module, class_name)
    return plugin_class()


def reload_plugins(plugins_dir: Path, enabled_keys: set[str]) -> PluginRegistry:
    global _registry
    manifests = {m.key: m for m in discover(plugins_dir)}
    instances = {}
    for key, manifest in manifests.items():
        if key in enabled_keys:
            instances[key] = _load_entrypoint(manifest)
    _registry = PluginRegistry(manifests=manifests, instances=instances)
    return _registry


def get_registry() -> PluginRegistry:
    return _registry


def dispatch_message_classified(message: dict[str, Any], classification: dict[str, Any]) -> None:
    for plugin in _registry.instances.values():
        hook = getattr(plugin, "on_message_classified", None)
        if callable(hook):
            hook(message, classification)
