from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr, entity_registry as er

from .const import DOMAIN

LOGGER = logging.getLogger(__name__)


async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = {}

    entity_reg = er.async_get(hass)
    device_reg = dr.async_get(hass)

    candidate_device_ids: set[str] = set()
    for ent in list(entity_reg.entities.values()):
        if getattr(ent, "device_id", None) is None:
            continue
        if ent.domain not in {"sensor", "select"}:
            continue
        if getattr(ent, "platform", None) != "tuya":
            continue

        haystack = " ".join(
            part
            for part in (
                ent.entity_id,
                getattr(ent, "unique_id", None) or "",
                getattr(ent, "original_name", None) or "",
                getattr(ent, "original_object_id", None) or "",
            )
            if part
        ).lower()
        if "switch_mode" not in haystack:
            continue

        candidate_device_ids.add(ent.device_id)

    LOGGER.debug(
        "Discovered %s candidate Tuya devices with action entities",
        len(candidate_device_ids),
    )

    attached = 0
    for device_id in candidate_device_ids:
        device = device_reg.async_get(device_id)
        if device is None:
            LOGGER.debug("Candidate device_id=%s not found in device registry", device_id)
            continue
        if not device.identifiers:
            LOGGER.debug(
                "Candidate device_id=%s has no identifiers, cannot attach config entry",
                device_id,
            )
            continue

        device_reg.async_get_or_create(
            config_entry_id=entry.entry_id,
            identifiers=set(device.identifiers),
        )
        attached += 1

    LOGGER.debug("Attached config entry to %s devices", attached)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    hass.data.get(DOMAIN, {}).pop(entry.entry_id, None)
    return True
