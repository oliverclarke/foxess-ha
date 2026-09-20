"""Time platform for the FoxESS Cloud integration (scheduler start/end)."""
from __future__ import annotations

import logging
from datetime import time as dt_time

from homeassistant.components.time import TimeEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .sensor import CONF_DEVICESN, DEFAULT_NAME, firstScheduleGroup

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up the FoxESS time entities from a config entry."""
    coordinator = hass.data[DOMAIN][entry.entry_id]
    name = DEFAULT_NAME
    deviceID = entry.data[CONF_DEVICESN]  # deviceSN and deviceID are the same value

    async_add_entities(
        [
            FoxESSScheduleStartTime(coordinator, name, deviceID),
            FoxESSScheduleEndTime(coordinator, name, deviceID),
        ]
    )


class FoxESSScheduleTimeBase(CoordinatorEntity, TimeEntity):
    """Start/end time for the locally-staged scheduler group.

    Values are only edited locally (coordinator.schedule_staging) - nothing is
    sent to FoxESS Cloud until the "Push Staged Schedule Group" button
    (button.py) is pressed. See sensor.py's FoxESSScheduleStaging.
    """

    def __init__(self, coordinator, name, deviceID):
        super().__init__(coordinator=coordinator)
        self._staging = coordinator.schedule_staging
        _LOGGER.debug("Initiating Entity - %s", self._nameValue)
        self._attr_name = f"{name} - {self._nameValue}"
        self._attr_unique_id = f"{deviceID}{self._uniqueValue}"

    @property
    def native_value(self) -> dt_time:
        return dt_time(
            hour=self._staging.group.get(self._hourKey) or 0,
            minute=self._staging.group.get(self._minuteKey) or 0,
        )

    async def async_set_value(self, value: dt_time) -> None:
        self._staging.group[self._hourKey] = value.hour
        self._staging.group[self._minuteKey] = value.minute
        self._staging.dirty = True
        self.async_write_ha_state()

    def _handle_coordinator_update(self) -> None:
        self._staging.sync_if_clean(firstScheduleGroup(self.coordinator.data))
        super()._handle_coordinator_update()


class FoxESSScheduleStartTime(FoxESSScheduleTimeBase):
    _hourKey = "startHour"
    _minuteKey = "startMinute"
    _nameValue = "Schedule Start Time"
    _uniqueValue = "schedule-start-time"


class FoxESSScheduleEndTime(FoxESSScheduleTimeBase):
    _hourKey = "endHour"
    _minuteKey = "endMinute"
    _nameValue = "Schedule End Time"
    _uniqueValue = "schedule-end-time"
