"""Number platform for the FoxESS Cloud integration."""
from __future__ import annotations

import logging

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import PERCENTAGE, UnitOfPower
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .sensor import CONF_APIKEY, CONF_DEVICESN, DEFAULT_NAME, setPeakShaving

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
        ]
    )


class FoxESSPeakShavingBase(CoordinatorEntity, NumberEntity):
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
