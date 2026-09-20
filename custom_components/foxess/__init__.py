"""The Foxess cloud integration."""
from __future__ import annotations

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import config_validation as cv

from .const import DOMAIN, PLATFORMS
from .sensor import CONF_APIKEY, CONF_DEVICESN, async_get_coordinator, setSchedule

SERVICE_SET_SCHEDULE = "set_schedule"
SET_SCHEDULE_SCHEMA = vol.Schema(
    {
        vol.Required("device_sn"): cv.string,
        vol.Required("groups"): vol.All(cv.ensure_list, [dict]),
        vol.Optional("is_default", default=False): cv.boolean,
    }
)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up FoxESS Cloud from a config entry."""
    entry.async_on_unload(entry.add_update_listener(async_update_listener))

    coordinator = await async_get_coordinator(hass, entry)
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    if not hass.services.has_service(DOMAIN, SERVICE_SET_SCHEDULE):
        hass.services.async_register(
            DOMAIN,
            SERVICE_SET_SCHEDULE,
            _make_set_schedule_handler(hass),
            schema=SET_SCHEDULE_SCHEMA,
        )

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        hass.data[DOMAIN].pop(entry.entry_id, None)
        if not hass.data[DOMAIN]:
            hass.services.async_remove(DOMAIN, SERVICE_SET_SCHEDULE)
    return unloaded


async def async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload the entry when its options are updated."""
    await hass.config_entries.async_reload(entry.entry_id)


def _make_set_schedule_handler(hass: HomeAssistant):
    """Build the foxess.set_schedule service handler.

    Replaces the entire scheduler table for the given inverter in one call -
    the only path that can set more than one time segment at once (the
    staging entities in select/number/time/button.py only ever edit group 0).
    """

    async def _handle_set_schedule(call: ServiceCall) -> None:
        deviceSn = call.data["device_sn"]
        groups = call.data["groups"]
        isDefault = call.data.get("is_default", False)

        targetEntry = next(
            (
                entry
                for entry in hass.config_entries.async_entries(DOMAIN)
                if entry.data.get(CONF_DEVICESN) == deviceSn
            ),
            None,
        )
        if targetEntry is None:
            raise HomeAssistantError(
                f"No configured FoxESS inverter with serial number {deviceSn}"
            )
        apiKey = targetEntry.options.get(CONF_APIKEY, targetEntry.data[CONF_APIKEY])

        error = await setSchedule(hass, deviceSn, apiKey, groups, isDefault)
        if error:
            raise HomeAssistantError(
                "FoxESS Cloud rejected the schedule change - check the Home "
                "Assistant log for details."
            )

        targetCoordinator = hass.data.get(DOMAIN, {}).get(targetEntry.entry_id)
        if targetCoordinator is not None:
            schedule = targetCoordinator.data.setdefault("settings", {}).setdefault(
                "schedule", {}
            )
            schedule["groups"] = groups
            targetCoordinator.async_update_listeners()
            await targetCoordinator.async_request_refresh()

    return _handle_set_schedule
