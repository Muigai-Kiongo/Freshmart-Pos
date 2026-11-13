from __future__ import annotations

from typing import Self

import httpx
import pytest

from app.core.config import Settings
from app.integrations.sms import (
    AfricasTalkingSmsProvider,
    DevSmsProvider,
    SmsDeliveryError,
    create_sms_provider,
)


class MockResponse:
    def __init__(self, payload: object, *, error: Exception | None = None) -> None:
        self.payload = payload
        self.error = error

    def raise_for_status(self) -> None:
        if self.error:
            raise self.error

    def json(self) -> object:
        return self.payload


class MockClient:
    response: MockResponse
    request: tuple[str, dict]

    def __init__(self, response: MockResponse) -> None:
        self.response = response
        self.request = ("", {})

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *_args) -> None:
        return None

    async def post(self, url: str, **kwargs) -> MockResponse:
        self.request = (url, kwargs)
        if self.response.error:
            raise self.response.error
        return self.response


def test_sms_provider_selection_requires_production_credentials() -> None:
    assert isinstance(
        create_sms_provider(Settings(_env_file=None, environment="test")),
        DevSmsProvider,
    )

    with pytest.raises(RuntimeError, match="credentials must be configured"):
        create_sms_provider(Settings(_env_file=None, environment="production"))

    provider = create_sms_provider(
        Settings(
            _env_file=None,
            environment="production",
            at_username="freshmart",
            at_api_key="not-a-real-key",
        )
    )
    assert isinstance(provider, AfricasTalkingSmsProvider)


async def test_africas_talking_sends_normalized_phone_and_message(monkeypatch) -> None:
    response = MockResponse({"SMSMessageData": {"Recipients": [{"status": "Success"}]}})
    client = MockClient(response)
    monkeypatch.setattr("app.integrations.sms.httpx.AsyncClient", lambda **_: client)
    provider = AfricasTalkingSmsProvider(
        username="freshmart", api_key="key", sender_id="DAZU"
    )

    await provider.send("254712345678", "Test message")

    url, options = client.request
    assert url == provider._endpoint
    assert options["headers"]["apiKey"] == "key"
    assert options["data"]["to"] == "+254712345678"
    assert options["data"]["message"] == "Test message"
    assert options["data"]["from"] == "DAZU"


@pytest.mark.parametrize(
    "payload",
    [
        [],
        {},
        {"SMSMessageData": {"Recipients": []}},
        {"SMSMessageData": {"Recipients": [{"status": "Failed"}]}},
    ],
)
async def test_africas_talking_rejects_unsuccessful_provider_responses(
    monkeypatch, payload
) -> None:
    client = MockClient(MockResponse(payload))
    monkeypatch.setattr("app.integrations.sms.httpx.AsyncClient", lambda **_: client)
    provider = AfricasTalkingSmsProvider(
        username="freshmart", api_key="key", sender_id="DAZU"
    )

    with pytest.raises(SmsDeliveryError):
        await provider.send("254712345678", "Test message")


async def test_africas_talking_wraps_http_errors(monkeypatch) -> None:
    request = httpx.Request("POST", "https://api.africastalking.com/version1/messaging")
    client = MockClient(
        MockResponse({}, error=httpx.ConnectError("offline", request=request))
    )
    monkeypatch.setattr("app.integrations.sms.httpx.AsyncClient", lambda **_: client)
    provider = AfricasTalkingSmsProvider(
        username="freshmart", api_key="key", sender_id="DAZU"
    )

    with pytest.raises(SmsDeliveryError, match="request failed"):
        await provider.send("254712345678", "Test message")
