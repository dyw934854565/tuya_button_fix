from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr, entity_registry as er

from .const import DOMAIN, LOGGER_NAME

LOGGER = logging.getLogger(LOGGER_NAME)


async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = {}

    entity_reg = er.async_get(hass)
    device_reg = dr.async_get(hass)

    tuya_like = 0
    tuya_like_with_device = 0
    action_device_entities: dict[str, list[str]] = {}
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

        matched = any(k in haystack for k in ("switch_mode", "switchmode", "action", "click", "press", "button", "key"))
        if not matched:
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
        if tuya_like <= 50:
            LOGGER.debug(
                "Tuya action candidate entity_id=%s domain=%s device_id=%s platform=%s unique_id=%s original_name=%s",
                ent.entity_id,
                ent.domain,
                ent.device_id,
                platform,
                getattr(ent, "unique_id", None),
                getattr(ent, "original_name", None),
            )

        action_device_entities.setdefault(ent.device_id, []).append(ent.entity_id)

    LOGGER.debug(
        "Tuya-like entities with device_id=%s, discovered %s devices with action entities",
        tuya_like_with_device,
        len(action_device_entities),
    )

    attached = 0
    for base_device_id, entity_ids in action_device_entities.items():
        base = device_reg.async_get(base_device_id)
        if base is None:
            LOGGER.debug("Candidate device_id=%s not found in device registry", base_device_id)
            continue
        if not base.identifiers:
            LOGGER.debug(
                "Candidate device_id=%s has no identifiers, cannot attach config entry (entities=%s)",
                base_device_id,
                entity_ids,
            )
            continue

        linked = device_reg.async_get_or_create(
            config_entry_id=entry.entry_id,
            identifiers=set(base.identifiers),
        )

        LOGGER.debug(
            "Linked config entry to device base_device_id=%s linked_id=%s name=%s action_entities=%s",
            base_device_id,
            linked.id,
            linked.name_by_user or linked.name,
            entity_ids,
        )
        attached += 1

    LOGGER.debug("Attached config entry to %s devices", attached)

    await hass.config_entries.async_forward_entry_setups(entry, ["device_trigger"])
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    await hass.config_entries.async_unload_platforms(entry, ["device_trigger"])
    hass.data.get(DOMAIN, {}).pop(entry.entry_id, None)
    return True
