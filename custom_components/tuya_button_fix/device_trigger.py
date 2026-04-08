from __future__ import annotations

from collections.abc import Awaitable, Callable
import logging

import voluptuous as vol

try:
    from homeassistant.const import CONF_SUBTYPE
except ImportError:
    CONF_SUBTYPE = "subtype"

from homeassistant.const import CONF_DEVICE_ID, CONF_DOMAIN, CONF_ENTITY_ID, CONF_PLATFORM, CONF_TYPE
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv, device_registry as dr, entity_registry as er
from homeassistant.helpers.event import async_track_state_change_event

from .const import DOMAIN, LOGGER_NAME, SCENE_DID, SCENE_ENTITY_ID, ALLOWED_DOMAINS

LOGGER = logging.getLogger(LOGGER_NAME)

_TRIGGER_BASE_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_PLATFORM): "device",
        vol.Required(CONF_DOMAIN): DOMAIN,
        vol.Required(CONF_DEVICE_ID): str,
    },
    extra=vol.ALLOW_EXTRA,
)

_INFO_LOGGED = False

# Only enable special "scene_click" mapping for these Tuya device ids
_SCENE_ONLY_TUYA_DEVICES: set[str] = {
    SCENE_DID,
}
_SCENE_ONLY_TUYA_ENTITY_IDS: set[str] = {
    SCENE_ENTITY_ID,
}


TRIGGER_TYPE_SINGLE = "single_click"
TRIGGER_TYPE_DOUBLE = "double_click"
TRIGGER_TYPE_LONG = "long_press"
TRIGGER_TYPE_SCENE = "scene_click"

TRIGGER_TYPES: tuple[str, ...] = (
    TRIGGER_TYPE_SINGLE,
    TRIGGER_TYPE_DOUBLE,
    TRIGGER_TYPE_LONG,
    TRIGGER_TYPE_SCENE,
)

STATE_MATCH: dict[str, set[str]] = {
    TRIGGER_TYPE_SINGLE: {"click", "single_click"},
    TRIGGER_TYPE_DOUBLE: {"double_click"},
    TRIGGER_TYPE_LONG: {"press", "long_press"},
    TRIGGER_TYPE_SCENE: {"scene"},
}

TRIGGER_SCHEMA = _TRIGGER_BASE_SCHEMA.extend(
    {
        vol.Required(CONF_ENTITY_ID): cv.entity_id,
        vol.Required(CONF_TYPE): vol.In(TRIGGER_TYPES),
        vol.Optional(CONF_SUBTYPE): cv.string,
    }
)

def _extract_subtype(entry: er.RegistryEntry) -> str:
    unique_id = (entry.unique_id or "").lower()
    for i in range(1, 9):
        if f"scene_{i}" in unique_id or f"scene{i}" in unique_id:
            return f"scene_{i}"
    for i in range(1, 9):
        if f"switch_mode{i}" in unique_id or f"switchmode{i}" in unique_id:
            return f"button_{i}"

    name = (getattr(entry, "original_name", None) or "").strip()
    for i in range(1, 9):
        if str(i) in name:
            return f"button_{i}"

    return "button"

def _trigger_types_for_entry(entry: er.RegistryEntry, base_device_id: str) -> tuple[str, ...]:
    unique_id = (entry.unique_id or "").lower()
    entity_id = (entry.entity_id or "").lower()
    original_name = (getattr(entry, "original_name", None) or "").lower()
    # Only expose scene triggers for whitelisted Tuya devices
    LOGGER.debug(
        "检查设备是否启用 scene_click：base_device_id=%s 在 _SCENE_ONLY_TUYA_DEVICES=%s，entity_id=%s 在 _SCENE_ONLY_TUYA_ENTITY_IDS=%s",
        base_device_id,
        base_device_id in _SCENE_ONLY_TUYA_DEVICES,
        entity_id,
        entity_id in _SCENE_ONLY_TUYA_ENTITY_IDS,
    )
    if base_device_id in _SCENE_ONLY_TUYA_DEVICES:
        if entity_id in _SCENE_ONLY_TUYA_ENTITY_IDS:
            LOGGER.debug("仅返回 scene_click 触发器")
            return (TRIGGER_TYPE_SCENE,)
        else:
            return ()
    LOGGER.debug("返回默认触发器类型：single_click、double_click、long_press")
    return (TRIGGER_TYPE_SINGLE, TRIGGER_TYPE_DOUBLE, TRIGGER_TYPE_LONG)


async def async_get_triggers(hass: HomeAssistant, device_id: str):
    global _INFO_LOGGED
    if not _INFO_LOGGED:
        LOGGER.info("device triggers requested")
        _INFO_LOGGED = True

    entity_reg = er.async_get(hass)
    device_reg = dr.async_get(hass)

    base_device_id = device_id
    device = device_reg.async_get(device_id)
    if device is not None:
        for domain, identifier in device.identifiers:
            if domain == DOMAIN:
                base_device_id = identifier
                break

    triggers: list[dict] = []
    entries = er.async_entries_for_device(entity_reg, base_device_id)
    LOGGER.debug(
        "async_get_triggers device_id=%s base_device_id=%s entity_count=%s",
        device_id,
        base_device_id,
        len(entries),
    )

    for entry in entries:
        
        if entry.domain not in ALLOWED_DOMAINS:
            continue

        subtype_detected = _extract_subtype(entry)
        # Show entity name together with subtype, to make UI labels clearer
        subtype_display = (getattr(entry, "original_name", None) or entry.entity_id or "").strip() or subtype_detected
        for trigger_type in _trigger_types_for_entry(entry, base_device_id):
            LOGGER.debug(
                "准备添加触发器：entity_id=%s trigger_type=%s original_name=%s subtype_detected=%s subtype_display=%s",
                entry.entity_id,
                getattr(entry, "original_name", None),
                trigger_type,
                subtype_detected,
                subtype_display,
            )
            triggers.append(
                {
                    CONF_PLATFORM: "device",
                    CONF_DOMAIN: DOMAIN,
                    CONF_DEVICE_ID: device_id,
                    CONF_ENTITY_ID: entry.entity_id,
                    CONF_TYPE: trigger_type,
                    CONF_SUBTYPE: subtype_display,
                }
            )

    LOGGER.debug("async_get_triggers device_id=%s triggers=%s", device_id, len(triggers))
    return triggers


async def async_validate_trigger_config(hass: HomeAssistant, config: dict) -> dict:
    return TRIGGER_SCHEMA(config)


async def async_attach_trigger(
    hass: HomeAssistant,
    config: dict,
    action: Callable[[dict], Awaitable[None]],
    trigger_info: dict,
):
    config = TRIGGER_SCHEMA(config)

    device_id_cfg: str = config[CONF_DEVICE_ID]
    entity_id: str = config[CONF_ENTITY_ID]
    trigger_type: str = config[CONF_TYPE]
    state_match = STATE_MATCH[trigger_type]
    subtype = config.get(CONF_SUBTYPE)

    LOGGER.debug(
        "attach_trigger device_id=%s entity_id=%s type=%s subtype=%s state_match=%s",
        device_id_cfg,
        entity_id,
        trigger_type,
        subtype,
        sorted(state_match),
    )

    async def _handle_event(event):
        LOGGER.debug(
            "state_change received device_id=%s cfg_entity_id=%s event_entity_id=%s old=%s new=%s",
            device_id_cfg,
            entity_id,
            event.data.get("entity_id"),
            event.data.get("old_state"),
            event.data.get("new_state"),
        )

        new_state = event.data.get("new_state")
        if new_state is None:
            return
        device_class = new_state.attributes.get('device_class')
        if device_class is not 'button':
            return
        event_type = new_state.attributes.get('event_type')
        if event_type is None:
            return
        if event_type not in state_match:
            return
        LOGGER.debug(
            "trigger fired device_id=%s entity_id=%s type=%s subtype=%s state=%s attrs=%s",
            device_id_cfg,
            entity_id,
            trigger_type,
            subtype,
            new_state.state,
            new_state.attributes,
        )

        hass.async_run_job(
            action,
            {
                **trigger_info,
                "platform": "device",
                "domain": DOMAIN,
                "device_id": device_id_cfg,
                "entity_id": entity_id,
                "type": trigger_type,
                "subtype": subtype,
            },
        )

    return async_track_state_change_event(hass, [entity_id], _handle_event)
