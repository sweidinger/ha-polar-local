"""Config flow for PETLIBRO Polar (local)."""
from __future__ import annotations

import re
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.const import CONF_NAME

from .const import CONF_SERIAL, DOMAIN

SERIAL_RE = re.compile(r"^[A-Z0-9]{8,32}$")


class PolarConfigFlow(ConfigFlow, domain=DOMAIN):
    """Ask for the serial number (shown in the Petlibro app and in MQTT topics)."""

    VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            serial = user_input[CONF_SERIAL].strip().upper()
            if not SERIAL_RE.match(serial):
                errors[CONF_SERIAL] = "invalid_serial"
            else:
                await self.async_set_unique_id(serial)
                self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title=user_input.get(CONF_NAME) or f"Polar {serial[-4:]}",
                    data={CONF_SERIAL: serial},
                )
        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({
                vol.Required(CONF_SERIAL): str,
                vol.Optional(CONF_NAME, default="Polar"): str,
            }),
            errors=errors,
        )
