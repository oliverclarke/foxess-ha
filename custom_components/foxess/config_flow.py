"""Config flow for the FoxESS Cloud integration."""
from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import callback
from homeassistant.data_entry_flow import FlowResult

from . import sensor as foxess_sensor
from .const import DOMAIN
from .sensor import (
    CONF_APIKEY,
    CONF_DEVICESN,
    CONF_EVO,
    CONF_EXTPV,
    CONF_GET_VARIABLES,
    CONF_V1_API,
    CONF_XTZONE,
    DEFAULT_NAME,
    getOADeviceDetail,
)

_LOGGER = logging.getLogger(__name__)


class InvalidAuth(Exception):
    """Error to indicate the API key or device serial number was rejected."""


async def _validate_credentials(
    hass, devicesn: str, apikey: str, v1_api: bool = True
) -> None:
    """Validate the API key/device SN against the FoxESS Cloud API.

    getOADeviceDetail() reads the V1_Api module global rather than taking it
    as an argument, so it has to be set before calling in.
    """
    foxess_sensor.V1_Api = v1_api
    allData = {"addressbook": {}, "raw": {}}
    error = await getOADeviceDetail(hass, allData, devicesn, apikey)
    if error:
        raise InvalidAuth


class FoxessConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for FoxESS Cloud."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle the initial step."""
        errors: dict[str, str] = {}

        if user_input is not None:
            devicesn = user_input[CONF_DEVICESN]
            apikey = user_input[CONF_APIKEY]

            await self.async_set_unique_id(devicesn)
            self._abort_if_unique_id_configured()

            try:
                await _validate_credentials(self.hass, devicesn, apikey)
            except InvalidAuth:
                errors["base"] = "invalid_auth"
            else:
                return self.async_create_entry(
                    title=f"{DEFAULT_NAME} ({devicesn})",
                    data={
                        CONF_DEVICESN: devicesn,
                        CONF_APIKEY: apikey,
                    },
                )

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_DEVICESN): str,
                    vol.Required(CONF_APIKEY): str,
                }
            ),
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> FoxessOptionsFlow:
        """Get the options flow for this handler."""
        return FoxessOptionsFlow(config_entry)


class FoxessOptionsFlow(config_entries.OptionsFlow):
    """Handle an options flow for FoxESS Cloud, e.g. to rotate the API key."""

    def __init__(self, config_entry: ConfigEntry) -> None:
        self.config_entry = config_entry

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Manage the options."""
        errors: dict[str, str] = {}
        current = {**self.config_entry.data, **self.config_entry.options}

        if user_input is not None:
            devicesn = self.config_entry.data[CONF_DEVICESN]

            try:
                await _validate_credentials(
                    self.hass,
                    devicesn,
                    user_input[CONF_APIKEY],
                    user_input[CONF_V1_API],
                )
            except InvalidAuth:
                errors["base"] = "invalid_auth"
            else:
                return self.async_create_entry(title="", data=user_input)

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_APIKEY, default=current.get(CONF_APIKEY)): str,
                    vol.Optional(
                        CONF_EXTPV, default=current.get(CONF_EXTPV, False)
                    ): bool,
                    vol.Optional(
                        CONF_XTZONE, default=current.get(CONF_XTZONE, False)
                    ): bool,
                    vol.Optional(
                        CONF_GET_VARIABLES,
                        default=current.get(CONF_GET_VARIABLES, False),
                    ): bool,
                    vol.Optional(
                        CONF_V1_API, default=current.get(CONF_V1_API, True)
                    ): bool,
                    vol.Optional(
                        CONF_EVO, default=current.get(CONF_EVO, False)
                    ): bool,
                }
            ),
            errors=errors,
        )
