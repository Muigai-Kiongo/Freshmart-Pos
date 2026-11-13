from __future__ import annotations

import logging
from typing import Protocol

import httpx

from app.core.config import Settings

logger = logging.getLogger(__name__)


class SmsDeliveryError(RuntimeError):
    pass


class SmsProvider(Protocol):
    async def send(self, phone: str, message: str) -> None: ...


class DevSmsProvider:
    async def send(self, phone: str, message: str) -> None:
        logger.info("Development SMS to +%s: %s", phone, message)


class AfricasTalkingSmsProvider:
    _endpoint = "https://api.africastalking.com/version1/messaging"

    def __init__(self, *, username: str, api_key: str, sender_id: str) -> None:
        self.username = username
        self.api_key = api_key
        self.sender_id = sender_id

    async def send(self, phone: str, message: str) -> None:
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.post(
                    self._endpoint,
                    headers={"apiKey": self.api_key, "Accept": "application/json"},
                    data={
                        "username": self.username,
                        "to": f"+{phone}",
                        "message": message,
                        "from": self.sender_id,
                    },
                )
                response.raise_for_status()
                payload = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise SmsDeliveryError("SMS provider request failed") from exc

        if not isinstance(payload, dict):
            raise SmsDeliveryError("SMS provider returned an invalid response")
        message_data = payload.get("SMSMessageData")
        recipients = (
            message_data.get("Recipients") if isinstance(message_data, dict) else None
        )
        if not isinstance(recipients, list) or not recipients:
            raise SmsDeliveryError("SMS provider did not accept the message")
        if any(
            not isinstance(recipient, dict) or recipient.get("status") != "Success"
            for recipient in recipients
        ):
            raise SmsDeliveryError("SMS provider did not accept the message")


def create_sms_provider(settings: Settings) -> SmsProvider:
    if settings.is_production:
        if not settings.at_username or not settings.at_api_key:
            raise RuntimeError(
                "Africa's Talking credentials must be configured in production"
            )
        return AfricasTalkingSmsProvider(
            username=settings.at_username,
            api_key=settings.at_api_key,
            sender_id=settings.at_sender_id,
        )
    return DevSmsProvider()
