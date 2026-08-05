from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.core.security import encrypt_secret
from app.db.models.plugin import PluginConfig
from app.services import plugin_manager

router = APIRouter(prefix="/plugins", tags=["plugins"])

PLUGINS_DIR = Path(__file__).resolve().parents[4] / "plugins"


class PluginOut(BaseModel):
    key: str
    name: str
    version: str
    is_enabled: bool


class PluginConfigUpdate(BaseModel):
    is_enabled: bool
    config: dict = {}


@router.get("", response_model=list[PluginOut])
def list_plugins(db: Session = Depends(get_db)) -> list[PluginOut]:
    manifests = plugin_manager.discover(PLUGINS_DIR)
    configs = {c.plugin_key: c for c in db.query(PluginConfig).all()}
    return [
        PluginOut(key=m.key, name=m.name, version=m.version, is_enabled=configs.get(m.key).is_enabled if m.key in configs else False)
        for m in manifests
    ]


@router.put("/{plugin_key}", response_model=PluginOut)
def update_plugin(plugin_key: str, payload: PluginConfigUpdate, db: Session = Depends(get_db)) -> PluginOut:
    manifests = {m.key: m for m in plugin_manager.discover(PLUGINS_DIR)}
    manifest = manifests.get(plugin_key)
    if manifest is None:
        raise HTTPException(status_code=404, detail="plugin not found")

    config = db.query(PluginConfig).filter(PluginConfig.plugin_key == plugin_key).one_or_none()
    if config is None:
        config = PluginConfig(plugin_key=plugin_key)
        db.add(config)
    config.is_enabled = payload.is_enabled
    import json

    config.config_json_encrypted = encrypt_secret(json.dumps(payload.config, ensure_ascii=False))
    db.commit()

    enabled_keys = {c.plugin_key for c in db.query(PluginConfig).filter(PluginConfig.is_enabled.is_(True)).all()}
    plugin_manager.reload_plugins(PLUGINS_DIR, enabled_keys)

    return PluginOut(key=manifest.key, name=manifest.name, version=manifest.version, is_enabled=config.is_enabled)
