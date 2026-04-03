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

    tuya_like = 0
    tuya_like_with_device = 0
    candidate_device_ids: set[str] = set()
    for ent in list(entity_reg.entities.values()):
        if getattr(ent, "device_id", None) is None:
            continue
        if ent.domain not in {"sensor", "select", "event"}:
            continue
        platform = getattr(ent, "platform", None)
        if not platform or "tuya" not in platform:
            continue

        tuya_like += 1
        tuya_like_with_device += 1

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

        if not any(k in haystack for k in ("switch_mode", "action", "click", "press")):
            if tuya_like <= 50:
                LOGGER.debug(
                    "Tuya-like entity skipped entity_id=%s domain=%s device_id=%s platform=%s unique_id=%s original_name=%s",
                    ent.entity_id,
                    ent.domain,
                    ent.device_id,
                    platform,
                    getattr(ent, "unique_id", None),
                    getattr(ent, "original_name", None),
                )
            continue

        candidate_device_ids.add(ent.device_id)

    LOGGER.debug(
        "Tuya-like entities with device_id=%s, discovered %s candidate devices with action entities",
        tuya_like_with_device,
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
