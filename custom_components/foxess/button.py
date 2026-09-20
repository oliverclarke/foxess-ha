"""Button platform for the FoxESS Cloud integration."""
from __future__ import annotations

import logging

from homeassistant.components.button import ButtonEntity
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
    setSchedule,
)

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up the FoxESS button entities from a config entry."""
    coordinator = hass.data[DOMAIN][entry.entry_id]
    name = DEFAULT_NAME
    deviceID = entry.data[CONF_DEVICESN]  # deviceSN and deviceID are the same value
    devicesn = entry.data[CONF_DEVICESN]
    apiKey = entry.options.get(CONF_APIKEY, entry.data[CONF_APIKEY])

    async_add_entities(
        [
            FoxESSSchedulePush(coordinator, name, deviceID, devicesn, apiKey),
            FoxESSScheduleRestore(coordinator, name, deviceID),
        ]
    )


class FoxESSSchedulePush(FoxESSEntity, ButtonEntity):
    """Push the locally-staged scheduler group (group 0) to FoxESS Cloud.

    Any other groups already on the inverter (e.g. set via the
    foxess.set_schedule service for a multi-segment program) are preserved -
    only group 0, the one editable through the staging entities, is replaced.
    """

    _attr_icon = "mdi:cloud-upload"

    def __init__(self, coordinator, name, deviceID, devicesn, apiKey):
        super().__init__(coordinator=coordinator)
        self._staging = coordinator.schedule_staging
        self._devicesn = devicesn
        self._apiKey = apiKey
        _LOGGER.debug("Initiating Entity - Push Staged Schedule Group")
        self._attr_name = f"{name} - Push Staged Schedule Group"
        self._attr_unique_id = f"{deviceID}schedule-push"

    async def async_press(self) -> None:
        existingGroups = self.coordinator.data.get("settings", {}).get(
            "schedule", {}
        ).get("groups") or [{}]
        groups = list(existingGroups)
        groups[0] = self._staging.group

        error = await setSchedule(self.hass, self._devicesn, self._apiKey, groups)
        if error:
            raise HomeAssistantError(
                "FoxESS Cloud rejected the schedule change - check the Home "
                "Assistant log for details."
            )

        self._staging.dirty = False
        schedule = self.coordinator.data.setdefault("settings", {}).setdefault(
            "schedule", {}
        )
        schedule["groups"] = groups
        self.async_write_ha_state()
        await self.coordinator.async_request_refresh()


class FoxESSScheduleRestore(FoxESSEntity, ButtonEntity):
    """Discard local edits to the staged scheduler group, re-syncing from the
    last poll (or FoxESS's defaults if nothing has ever been fetched).
    """

    _attr_icon = "mdi:restore"

    def __init__(self, coordinator, name, deviceID):
        super().__init__(coordinator=coordinator)
        self._staging = coordinator.schedule_staging
        _LOGGER.debug("Initiating Entity - Restore Staged Schedule Group")
        self._attr_name = f"{name} - Restore Staged Schedule Group"
        self._attr_unique_id = f"{deviceID}schedule-restore"

    async def async_press(self) -> None:
        groups = self.coordinator.data.get("settings", {}).get("schedule", {}).get(
            "groups"
        ) or []
        self._staging.restore(groups[0] if groups else None)
        # the staging object is shared by several separate entity instances
        # across select/number/time.py - notify all of them now rather than
        # waiting for the next poll (no network call, just a local refresh)
        self.coordinator.async_update_listeners()
