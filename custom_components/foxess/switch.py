"""Switch platform for the FoxESS Cloud integration."""
from __future__ import annotations

import logging

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .sensor import (
    CONF_APIKEY,
    CONF_DEVICESN,
    DEFAULT_NAME,
    FoxESSEntity,
    setScheduleFlag,
)

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up the FoxESS switch entities from a config entry."""
    coordinator = hass.data[DOMAIN][entry.entry_id]
    name = DEFAULT_NAME
    deviceID = entry.data[CONF_DEVICESN]  # deviceSN and deviceID are the same value
    devicesn = entry.data[CONF_DEVICESN]
    apiKey = entry.options.get(CONF_APIKEY, entry.data[CONF_APIKEY])

    async_add_entities(
        [FoxESSScheduleEnable(coordinator, name, deviceID, devicesn, apiKey)]
    )


class FoxESSScheduleEnable(FoxESSEntity, SwitchEntity):
    """Master on/off switch for the inverter's scheduler.

    Reads the cached value from the ~hourly getSchedule() poll rather than
    calling the live /scheduler/get/flag endpoint on every state read - that
    endpoint is still called live, separately, as a safety check right before
    a plain work mode change (see select.py's FoxESSWorkMode).
    """

    _attr_icon = "mdi:calendar-clock"

    def __init__(self, coordinator, name, deviceID, devicesn, apiKey):
        super().__init__(coordinator=coordinator)
        self._devicesn = devicesn
        self._apiKey = apiKey
        _LOGGER.debug("Initiating Entity - Schedule Enabled")
        self._attr_name = f"{name} - Schedule Enabled"
        self._attr_unique_id = f"{deviceID}schedule-enabled"

    @property
    def is_on(self) -> bool | None:
        return self.coordinator.data.get("settings", {}).get("schedule", {}).get(
            "enable"
        )

    async def _async_set(self, enable: bool) -> None:
        error = await setScheduleFlag(self.hass, self._devicesn, self._apiKey, enable)
        if error:
            raise HomeAssistantError(
                "FoxESS Cloud rejected the schedule enable/disable change - "
                "check the Home Assistant log for details."
            )
        schedule = self.coordinator.data.setdefault("settings", {}).setdefault(
            "schedule", {}
        )
        schedule["enable"] = enable
        self.async_write_ha_state()
        await self.coordinator.async_request_refresh()

    async def async_turn_on(self, **kwargs) -> None:
        await self._async_set(True)

    async def async_turn_off(self, **kwargs) -> None:
        await self._async_set(False)
