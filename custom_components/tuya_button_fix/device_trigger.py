from __future__ import annotations

from collections.abc import Awaitable, Callable
import logging

import voluptuous as vol

from homeassistant.const import CONF_DEVICE_ID, CONF_DOMAIN, CONF_ENTITY_ID, CONF_PLATFORM, CONF_TYPE
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv, entity_registry as er
from homeassistant.helpers import device_trigger as device_trigger_helper
from homeassistant.helpers.event import async_track_state_change_event

from .const import DOMAIN, SUPPORTED_ATTRS

LOGGER = logging.getLogger(__name__)

TRIGGER_TYPE_SINGLE = "single_click"
TRIGGER_TYPE_DOUBLE = "double_click"
TRIGGER_TYPE_LONG = "long_press"

TRIGGER_TYPES: tuple[str, ...] = (
    TRIGGER_TYPE_SINGLE,
    TRIGGER_TYPE_DOUBLE,
    TRIGGER_TYPE_LONG,
)

STATE_MATCH: dict[str, set[str]] = {
    TRIGGER_TYPE_SINGLE: {"click", "single_click"},
    TRIGGER_TYPE_DOUBLE: {"double_click"},
    TRIGGER_TYPE_LONG: {"press", "long_press"},
}

TRIGGER_SCHEMA = device_trigger_helper.DEVICE_TRIGGER_BASE_SCHEMA.extend(
    {
        vol.Required(CONF_ENTITY_ID): cv.entity_id,
        vol.Required(CONF_TYPE): vol.In(TRIGGER_TYPES),
    }
)


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
    return "switch_mode" in haystack


async def async_get_triggers(hass: HomeAssistant, device_id: str):
    entity_reg = er.async_get(hass)

    triggers: list[dict] = []
    entries = er.async_entries_for_device(entity_reg, device_id)
    LOGGER.debug("async_get_triggers device_id=%s entity_count=%s", device_id, len(entries))

    for entry in entries:
        if entry.domain not in {"sensor", "select"}:
            continue
        if not _looks_like_action_entity(entry):
            continue

        for trigger_type in TRIGGER_TYPES:
            triggers.append(
                {
                    CONF_PLATFORM: "device",
                    CONF_DOMAIN: DOMAIN,
                    CONF_DEVICE_ID: device_id,
                    CONF_ENTITY_ID: entry.entity_id,
                    CONF_TYPE: trigger_type,
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

    async def _handle_event(event):
        new_state = event.data.get("new_state")
        if new_state is None:
            return

        ok = str(new_state.state) in state_match
        if not ok:
            for attr in SUPPORTED_ATTRS:
                val = new_state.attributes.get(attr)
                if val and str(val) in state_match:
                    ok = True
                    break
        if not ok:
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
            },
        )

    LOGGER.debug("attach_trigger entity_id=%s type=%s", entity_id, trigger_type)
    return async_track_state_change_event(hass, [entity_id], _handle_event)
