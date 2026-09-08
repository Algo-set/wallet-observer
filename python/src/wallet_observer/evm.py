"""Closed, read-only EVM JSON-RPC adapter."""

import asyncio
import json
import re
from decimal import Decimal
from urllib.parse import urlsplit

import httpx

from ._validation import ObserverError, integer
from .provider import BalanceRequest, ProviderBalance, ProviderFailure

_ALLOWED_METHODS = frozenset({"eth_chainId", "eth_getBalance", "eth_call"})
MAX_RESPONSE_BYTES = 1024 * 1024


def normalize_address(value: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"0x[0-9a-fA-F]{40}", value):
        raise ProviderFailure("invalid_account_or_asset_reference")
    return value.lower()


def encode_balance_query(owner: str) -> str:
    return "0x70a08231" + normalize_address(owner)[2:].rjust(64, "0")


def quantity_from_atomic(value: int, decimals: int) -> Decimal:
    try:
        integer(decimals, 0, 28)
    except ObserverError:
        raise ProviderFailure("unsupported_asset_decimals") from None
    try:
        integer(value, 0, 2**128 - 1)
    except ObserverError:
        raise ProviderFailure("invalid_provider_quantity") from None
    return Decimal((0, tuple(int(d) for d in str(value)), -decimals))


def _hex_quantity(value: object, bits: int = 128) -> int:
    if not isinstance(value, str) or not re.fullmatch(r"0x[0-9a-fA-F]{1,64}", value):
        raise ProviderFailure("invalid_provider_quantity")
    result = int(value[2:], 16)
    if result >= 2**bits:
        raise ProviderFailure("invalid_provider_quantity")
    return result


class EvmRpcClient:
    def __init__(self, endpoint: str, *, transport: httpx.AsyncBaseTransport | None = None):
        try:
            parts = urlsplit(endpoint)
            if (
                parts.scheme not in ("http", "https")
                or not parts.hostname
                or parts.username is not None
                or parts.password is not None
                or parts.fragment
                or parts.port == 0
                or any(c.isspace() for c in endpoint)
            ):
                raise ValueError
        except (ValueError, TypeError, AttributeError):
            raise ProviderFailure("invalid_provider_endpoint") from None
        self._endpoint = endpoint
        self._client = httpx.AsyncClient(
            timeout=10,
            follow_redirects=False,
            trust_env=False,
            transport=transport,
            headers={"User-Agent": "wallet-observer-python/0.1"},
        )
        self._request_id = 0

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        await self.aclose()

    async def aclose(self):
        await self._client.aclose()

    async def chain_id(self) -> int:
        return _hex_quantity(await self._call("eth_chainId", []), 64)

    async def native_balance(self, address: str) -> int:
        return _hex_quantity(
            await self._call("eth_getBalance", [normalize_address(address), "latest"])
        )

    async def token_balance(self, token: str, owner: str) -> int:
        query = {"to": normalize_address(token), "data": encode_balance_query(owner)}
        return _hex_quantity(await self._call("eth_call", [query, "latest"]))

    async def _call(self, method: str, params: list):
        if method not in _ALLOWED_METHODS:
            raise ProviderFailure("provider_method_not_allowed")
        self._request_id += 1
        request_id = self._request_id
        try:
            async with (
                asyncio.timeout(10),
                self._client.stream(
                    "POST",
                    self._endpoint,
                    json={
                        "jsonrpc": "2.0",
                        "id": request_id,
                        "method": method,
                        "params": params,
                    },
                ) as response,
            ):
                response.raise_for_status()
                body = bytearray()
                async for chunk in response.aiter_bytes():
                    body.extend(chunk)
                    if len(body) > MAX_RESPONSE_BYTES:
                        raise ProviderFailure("provider_response_error")
            data = json.loads(body)
        except (httpx.RequestError, TimeoutError):
            raise ProviderFailure("provider_network_error") from None
        except (httpx.HTTPStatusError, ValueError, UnicodeError, RecursionError):
            raise ProviderFailure("provider_response_error") from None
        if (
            not isinstance(data, dict)
            or data.get("jsonrpc") != "2.0"
            or type(data.get("id")) is not int
            or data["id"] != request_id
            or "error" in data
            or "result" not in data
        ):
            raise ProviderFailure("provider_response_error")
        return data["result"]


class EvmBalanceProvider:
    def __init__(self, endpoint: str, *, transport: httpx.AsyncBaseTransport | None = None):
        self._client = EvmRpcClient(endpoint, transport=transport)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        await self.aclose()

    async def aclose(self):
        await self._client.aclose()

    async def verify_chain_id(self, expected: int):
        integer(expected, 0, 2**64 - 1)
        if await self._client.chain_id() != expected:
            raise ProviderFailure("chain_id_mismatch")

    async def balance(self, request: BalanceRequest) -> ProviderBalance:
        if request.asset_reference is None:
            atomic = await self._client.native_balance(request.account_reference)
        else:
            atomic = await self._client.token_balance(
                request.asset_reference, request.account_reference
            )
        return ProviderBalance(atomic, quantity_from_atomic(atomic, request.decimals))
