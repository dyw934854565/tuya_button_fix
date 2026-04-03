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

from .const import DOMAIN, LOGGER_NAME, SUPPORTED_ATTRS

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
    "6c4fa5eaa2b73d87fdf9cp",
}

ALLOWED_DOMAINS: set[str] = {
    "binary_sensor",
    "button",
    "event",
    "number",
    "select",
    "sensor",
    "switch",
    "text",
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
    if base_device_id in _SCENE_ONLY_TUYA_DEVICES and (
        "scene_" in unique_id or "scene_" in entity_id or "scene" in original_name
    ):
        return (TRIGGER_TYPE_SCENE,)
    return (TRIGGER_TYPE_SINGLE, TRIGGER_TYPE_DOUBLE, TRIGGER_TYPE_LONG)

def _iter_action_strings(value):
    if value is None:
        return
    if isinstance(value, str):
        yield value
        return
    if isinstance(value, (int, float, bool)):
        yield str(value)
        return
    if isinstance(value, dict):
        for v in value.values():
            yield from _iter_action_strings(v)
        return
    if isinstance(value, (list, tuple, set)):
        for v in value:
            yield from _iter_action_strings(v)
        return
    yield str(value)


def _looks_like_action_entity(entry: er.RegistryEntry) -> bool:
    haystack = " ".join(
        part
        for part in (
            entry.entity_id,
            entry.unique_id or "",
            getattr(entry, "original_name", None) or "",
            getattr(entry, "original_object_id", None) or "",
        )
        if part
    ).lower()
    return any(
        k in haystack
        for k in (
            "switch_mode",
            "switchmode",
            "action",
            "click",
            "double",
            "press",
            "long",
            "button",
            "key",
            "scene",
        )
    )


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

    logged = 0
    for entry in entries:
        if logged < 50:
            LOGGER.debug(
                "device entity entity_id=%s domain=%s unique_id=%s original_name=%s platform=%s",
                entry.entity_id,
                entry.domain,
                getattr(entry, "unique_id", None),
                getattr(entry, "original_name", None),
                getattr(entry, "platform", None),
            )
            logged += 1

        if entry.domain not in ALLOWED_DOMAINS:
            continue
        if not _looks_like_action_entity(entry):
            continue

        subtype_detected = _extract_subtype(entry)
        # Show entity name together with subtype, to make UI labels clearer
        subtype_display = (getattr(entry, "original_name", None) or entry.entity_id or "").strip() or subtype_detected
        for trigger_type in _trigger_types_for_entry(entry, base_device_id):
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

    entity_id: str = config[CONF_ENTITY_ID]
    trigger_type: str = config[CONF_TYPE]
    state_match = STATE_MATCH[trigger_type]
    subtype = config.get(CONF_SUBTYPE)

    async def _handle_event(event):
        new_state = event.data.get("new_state")
        if new_state is None:
            return

        ok = False
        seen: set[str] = set()
        for s in _iter_action_strings(new_state.state):
            s = str(s)
            if s:
                seen.add(s)
                if s in state_match:
                    ok = True
                    break

        if not ok:
            for attr in SUPPORTED_ATTRS:
                if attr not in new_state.attributes:
                    continue
                val = new_state.attributes.get(attr)
                for s in _iter_action_strings(val):
                    s = str(s)
                    if s:
                        seen.add(s)
                        if s in state_match:
                            ok = True
                            break
                if ok:
                    break

        if not ok:
            LOGGER.debug(
                "trigger not matched entity_id=%s type=%s candidates=%s",
                entity_id,
                trigger_type,
                sorted(seen)[:20],
            )
            return

        LOGGER.debug(
            "trigger fired entity_id=%s type=%s state=%s attrs=%s",
            entity_id,
            trigger_type,
            new_state.state,
            {k: new_state.attributes.get(k) for k in SUPPORTED_ATTRS if k in new_state.attributes},
        )

        hass.async_run_job(
            action,
            {
                **trigger_info,
                "platform": "device",
                "domain": DOMAIN,
                "device_id": config[CONF_DEVICE_ID],
                "entity_id": entity_id,
                "type": trigger_type,
                "subtype": subtype,
            },
        )

    LOGGER.debug("attach_trigger entity_id=%s type=%s subtype=%s", entity_id, trigger_type, subtype)
    return async_track_state_change_event(hass, [entity_id], _handle_event)
