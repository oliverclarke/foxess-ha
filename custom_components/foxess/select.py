"""Select platform for the FoxESS Cloud integration."""
from __future__ import annotations

import logging

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .sensor import (
    CONF_APIKEY,
    CONF_DEVICESN,
    DEFAULT_NAME,
    SCHEDULE_WORK_MODES,
    WORK_MODES,
    firstScheduleGroup,
    getScheduleEnabled,
    setWorkMode,
)

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up the FoxESS select entities from a config entry."""
    coordinator = hass.data[DOMAIN][entry.entry_id]
    name = DEFAULT_NAME
    deviceID = entry.data[CONF_DEVICESN]  # deviceSN and deviceID are the same value
    devicesn = entry.data[CONF_DEVICESN]
    apiKey = entry.options.get(CONF_APIKEY, entry.data[CONF_APIKEY])

    async_add_entities(
        [
            FoxESSWorkMode(coordinator, name, deviceID, devicesn, apiKey),
            FoxESSScheduleWorkMode(coordinator, name, deviceID),
        ]
    )


class FoxESSWorkMode(CoordinatorEntity, SelectEntity):
    _attr_options = WORK_MODES
    _attr_icon = "mdi:home-battery"

    def __init__(self, coordinator, name, deviceID, devicesn, apiKey):
        super().__init__(coordinator=coordinator)
        self._devicesn = devicesn
        self._apiKey = apiKey
        _LOGGER.debug("Initiating Entity - Work Mode")
        self._attr_name = f"{name} - Work Mode"
        self._attr_unique_id = f"{deviceID}work-mode"

    @property
    def current_option(self) -> str | None:
        workMode = self.coordinator.data.get("settings", {}).get("workMode")
        if workMode not in self.options:
            _LOGGER.debug("Work Mode %s not in known options", workMode)
            return None
        return workMode

    async def async_select_option(self, option: str) -> None:
        scheduleEnabled = await getScheduleEnabled(
            self.hass, self._devicesn, self._apiKey
        )
        if scheduleEnabled:
            raise HomeAssistantError(
                "Cannot change work mode: a schedule is currently active on the "
                "inverter. Turn off the Schedule Enabled switch (or disable it "
                "in the FoxESS app) first, then try again."
            )

        error = await setWorkMode(self.hass, self._devicesn, self._apiKey, option)
        if error:
            raise HomeAssistantError(
                "FoxESS Cloud rejected the work mode change - check the Home "
                "Assistant log for details."
            )

        self.coordinator.data.setdefault("settings", {})["workMode"] = option
        self.async_write_ha_state()
        await self.coordinator.async_request_refresh()


class FoxESSScheduleWorkMode(CoordinatorEntity, SelectEntity):
    """Work mode for the locally-staged scheduler group (not applied until
    pushed via the "Push Staged Schedule Group" button in button.py).
    """

    _attr_options = SCHEDULE_WORK_MODES
    _attr_icon = "mdi:calendar-sync"

    def __init__(self, coordinator, name, deviceID):
        super().__init__(coordinator=coordinator)
        self._staging = coordinator.schedule_staging
        _LOGGER.debug("Initiating Entity - Schedule Work Mode")
        self._attr_name = f"{name} - Schedule Work Mode"
        self._attr_unique_id = f"{deviceID}schedule-work-mode"

    @property
    def current_option(self) -> str | None:
        return self._staging.group.get("workMode")

    async def async_select_option(self, option: str) -> None:
        self._staging.group["workMode"] = option
        self._staging.dirty = True
        self.async_write_ha_state()

    def _handle_coordinator_update(self) -> None:
        self._staging.sync_if_clean(firstScheduleGroup(self.coordinator.data))
        super()._handle_coordinator_update()
