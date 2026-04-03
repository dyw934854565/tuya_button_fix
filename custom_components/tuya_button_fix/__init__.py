from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr, entity_registry as er

from .const import DOMAIN


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = {}

    entity_reg = er.async_get(hass)
    device_reg = dr.async_get(hass)

    device_candidates: dict[str, list[str]] = {}
    for e in list(entity_reg.entities.values()):
        if e.platform != "tuya":
            continue
        if e.domain not in {"sensor", "select"}:
            continue
        text = " ".join(
            p
            for p in (
                e.entity_id,
                e.original_object_id or "",
                e.original_name or "",
            )
            if p
        ).lower()
        if "switch_mode" not in text:
            continue
        if e.device_id:
            device_candidates.setdefault(e.device_id, []).append(e.entity_id)

    mirror_map: dict[str, str] = {}
    for base_device_id, entity_ids in device_candidates.items():
        base_device = device_reg.async_get(base_device_id)
        if base_device is None:
            continue
        mirror = device_reg.async_get_or_create(
            config_entry_id=entry.entry_id,
            identifiers={(DOMAIN, base_device_id)},
            name=(base_device.name_by_user or base_device.name or "Tuya Button") + " Buttons",
            manufacturer=base_device.manufacturer or "Tuya",
            model=(base_device.model or "") + " Button",
            via_device_id=base_device_id,
        )
        mirror_map[mirror.id] = base_device_id

    hass.data[DOMAIN][entry.entry_id]["mirror_map"] = mirror_map
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    hass.data.get(DOMAIN, {}).pop(entry.entry_id, None)
    return True
