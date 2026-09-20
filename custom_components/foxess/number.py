"""Number platform for the FoxESS Cloud integration."""
from __future__ import annotations

import logging

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import PERCENTAGE, UnitOfPower
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .sensor import (
    CONF_APIKEY,
    CONF_DEVICESN,
    DEFAULT_NAME,
    FoxESSEntity,
    firstScheduleGroup,
    setPeakShaving,
)

_LOGGER = logging.getLogger(__name__)

# used until the first successful poll has returned FoxESS's own range for this inverter
DEFAULT_IMPORT_LIMIT_MIN = 0
DEFAULT_IMPORT_LIMIT_MAX = 30000


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up the FoxESS number entities from a config entry."""
    coordinator = hass.data[DOMAIN][entry.entry_id]
    name = DEFAULT_NAME
    deviceID = entry.data[CONF_DEVICESN]  # deviceSN and deviceID are the same value
    devicesn = entry.data[CONF_DEVICESN]
    apiKey = entry.options.get(CONF_APIKEY, entry.data[CONF_APIKEY])

    async_add_entities(
        [
            FoxESSPeakShavingImportLimit(
                coordinator, name, deviceID, devicesn, apiKey
            ),
            FoxESSPeakShavingSoc(coordinator, name, deviceID, devicesn, apiKey),
            FoxESSScheduleFdSoc(coordinator, name, deviceID),
            FoxESSScheduleFdPwr(coordinator, name, deviceID),
            FoxESSScheduleImportLimit(coordinator, name, deviceID),
            FoxESSScheduleExportLimit(coordinator, name, deviceID),
            FoxESSSchedulePvLimit(coordinator, name, deviceID),
        ]
    )


class FoxESSPeakShavingBase(FoxESSEntity, NumberEntity):
    """Common paired-value handling for the peakShaving/set endpoint.

    FoxESS requires both importLimit and soc on every write, so setting one
    of these entities re-sends the other's last known (polled) value.
    """

    def __init__(self, coordinator, name, deviceID, devicesn, apiKey):
        super().__init__(coordinator=coordinator)
        self._devicesn = devicesn
        self._apiKey = apiKey
        _LOGGER.debug("Initiating Entity - %s", self._nameValue)
        self._attr_name = f"{name} - {self._nameValue}"
        self._attr_unique_id = f"{deviceID}{self._uniqueValue}"

    def _current_pair(self):
        settings = self.coordinator.data.get("settings", {})
        return settings.get("peakShavingImportLimit"), settings.get("peakShavingSoc")

    async def _async_set_pair(self, importLimit: float, soc: int) -> None:
        error = await setPeakShaving(
            self.hass, self._devicesn, self._apiKey, importLimit, soc
        )
        if error:
            raise HomeAssistantError(
                "FoxESS Cloud rejected the peak shaving change - check the Home "
                "Assistant log for details."
            )
        settings = self.coordinator.data.setdefault("settings", {})
        settings["peakShavingImportLimit"] = importLimit
        settings["peakShavingSoc"] = soc
        self.async_write_ha_state()
        await self.coordinator.async_request_refresh()


class FoxESSPeakShavingImportLimit(FoxESSPeakShavingBase):
    _attr_mode = NumberMode.BOX
    _attr_native_unit_of_measurement = UnitOfPower.WATT
    _nameValue = "Peak Shaving Power Limit"
    _uniqueValue = "peak-shaving-power-limit"

    @property
    def native_min_value(self) -> float:
        rangeData = self.coordinator.data.get("settings", {}).get(
            "peakShavingImportLimitRange"
        )
        if rangeData and rangeData.get("min") is not None:
            return float(rangeData["min"])
        return DEFAULT_IMPORT_LIMIT_MIN

    @property
    def native_max_value(self) -> float:
        rangeData = self.coordinator.data.get("settings", {}).get(
            "peakShavingImportLimitRange"
        )
        if rangeData and rangeData.get("max") is not None:
            return float(rangeData["max"])
        return DEFAULT_IMPORT_LIMIT_MAX

    @property
    def native_step(self) -> float:
        precision = self.coordinator.data.get("settings", {}).get(
            "peakShavingImportLimitPrecision"
        )
        if precision:
            return float(precision)
        return 1

    @property
    def native_value(self) -> float | None:
        return self._current_pair()[0]

    async def async_set_native_value(self, value: float) -> None:
        _, soc = self._current_pair()
        if soc is None:
            raise HomeAssistantError(
                "Peak shaving SOC threshold hasn't been read from FoxESS Cloud "
                "yet - wait for the next update and try again."
            )
        await self._async_set_pair(value, soc)


class FoxESSPeakShavingSoc(FoxESSPeakShavingBase):
    _attr_mode = NumberMode.SLIDER
    _attr_native_unit_of_measurement = PERCENTAGE
    _nameValue = "Peak Shaving SOC Threshold"
    _uniqueValue = "peak-shaving-soc-threshold"

    @property
    def native_min_value(self) -> float:
        rangeData = self.coordinator.data.get("settings", {}).get(
            "peakShavingSocRange"
        )
        if rangeData and rangeData.get("min") is not None:
            return float(rangeData["min"])
        return 0

    @property
    def native_max_value(self) -> float:
        rangeData = self.coordinator.data.get("settings", {}).get(
            "peakShavingSocRange"
        )
        if rangeData and rangeData.get("max") is not None:
            return float(rangeData["max"])
        return 100

    @property
    def native_step(self) -> float:
        precision = self.coordinator.data.get("settings", {}).get(
            "peakShavingSocPrecision"
        )
        if precision:
            return float(precision)
        return 1

    @property
    def native_value(self) -> float | None:
        return self._current_pair()[1]

    async def async_set_native_value(self, value: float) -> None:
        importLimit, _ = self._current_pair()
        if importLimit is None:
            raise HomeAssistantError(
                "Peak shaving power limit hasn't been read from FoxESS Cloud yet "
                "- wait for the next update and try again."
            )
        await self._async_set_pair(importLimit, int(value))


class FoxESSScheduleNumberBase(FoxESSEntity, NumberEntity):
    """Common handling for a locally-staged scheduler group's extraParam field.

    Values are only edited locally (coordinator.schedule_staging) - nothing is
    sent to FoxESS Cloud until the "Push Staged Schedule Group" button
    (button.py) is pressed. See sensor.py's FoxESSScheduleStaging.
    """

    _attr_mode = NumberMode.BOX

    def __init__(self, coordinator, name, deviceID):
        super().__init__(coordinator=coordinator)
        self._staging = coordinator.schedule_staging
        _LOGGER.debug("Initiating Entity - %s", self._nameValue)
        self._attr_name = f"{name} - {self._nameValue}"
        self._attr_unique_id = f"{deviceID}{self._uniqueValue}"

    def _propertyRange(self):
        properties = self.coordinator.data.get("settings", {}).get(
            "schedule", {}
        ).get("properties", {})
        return properties.get(self._paramKey) or {}

    @property
    def native_min_value(self) -> float:
        rangeData = self._propertyRange().get("range")
        if rangeData and rangeData.get("min") is not None:
            return float(rangeData["min"])
        return self._defaultMin

    @property
    def native_max_value(self) -> float:
        rangeData = self._propertyRange().get("range")
        if rangeData and rangeData.get("max") is not None:
            return float(rangeData["max"])
        return self._defaultMax

    @property
    def native_step(self) -> float:
        precision = self._propertyRange().get("precision")
        if precision:
            return float(precision)
        return 1

    @property
    def native_value(self) -> float | None:
        value = self._staging.group.get("extraParam", {}).get(self._paramKey)
        return float(value) if value is not None else None

    async def async_set_native_value(self, value: float) -> None:
        self._staging.group.setdefault("extraParam", {})[self._paramKey] = value
        self._staging.dirty = True
        self.async_write_ha_state()

    def _handle_coordinator_update(self) -> None:
        self._staging.sync_if_clean(firstScheduleGroup(self.coordinator.data))
        super()._handle_coordinator_update()


class FoxESSScheduleFdSoc(FoxESSScheduleNumberBase):
    _attr_native_unit_of_measurement = PERCENTAGE
    _paramKey = "fdSoc"
    _nameValue = "Schedule Charging Cut-off SOC"
    _uniqueValue = "schedule-fd-soc"
    _defaultMin = 0
    _defaultMax = 100


class FoxESSScheduleFdPwr(FoxESSScheduleNumberBase):
    _attr_native_unit_of_measurement = UnitOfPower.WATT
    _paramKey = "fdPwr"
    _nameValue = "Schedule Charge Power from Grid"
    _uniqueValue = "schedule-fd-pwr"
    _defaultMin = DEFAULT_IMPORT_LIMIT_MIN
    _defaultMax = DEFAULT_IMPORT_LIMIT_MAX


class FoxESSScheduleImportLimit(FoxESSScheduleNumberBase):
    _attr_native_unit_of_measurement = UnitOfPower.WATT
    _paramKey = "importLimit"
    _nameValue = "Schedule Import Limit"
    _uniqueValue = "schedule-import-limit"
    _defaultMin = DEFAULT_IMPORT_LIMIT_MIN
    _defaultMax = DEFAULT_IMPORT_LIMIT_MAX


class FoxESSScheduleExportLimit(FoxESSScheduleNumberBase):
    _attr_native_unit_of_measurement = UnitOfPower.WATT
    _paramKey = "exportLimit"
    _nameValue = "Schedule Export Limit"
    _uniqueValue = "schedule-export-limit"
    _defaultMin = DEFAULT_IMPORT_LIMIT_MIN
    _defaultMax = DEFAULT_IMPORT_LIMIT_MAX


class FoxESSSchedulePvLimit(FoxESSScheduleNumberBase):
    """Best-effort stand-in for the FoxESS app's "Charge from PV" toggle.

    FoxESS's OpenAPI doesn't document a distinct boolean for this - pvLimit
    is the closest documented field. Unconfirmed against real hardware.
    """

    _attr_native_unit_of_measurement = UnitOfPower.WATT
    _paramKey = "pvLimit"
    _nameValue = "Schedule Charge from PV Limit"
    _uniqueValue = "schedule-pv-limit"
    _defaultMin = DEFAULT_IMPORT_LIMIT_MIN
    _defaultMax = DEFAULT_IMPORT_LIMIT_MAX
