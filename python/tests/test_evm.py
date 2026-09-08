import json

import httpx
import pytest

from wallet_observer import BalanceRequest, EvmBalanceProvider, EvmRpcClient, ProviderFailure
from wallet_observer.evm import MAX_RESPONSE_BYTES, encode_balance_query, normalize_address

ADDRESS = "0x" + "12" * 20
TOKEN = "0x" + "ab" * 20


def test_address_and_query_encoding():
    assert normalize_address(TOKEN.upper().replace("0X", "0x")) == TOKEN
    assert encode_balance_query(ADDRESS) == "0x70a08231" + "0" * 24 + "12" * 20


@pytest.mark.parametrize("value", ["bad", "0x1234", "0x" + "g" * 40, None])
def test_invalid_address(value):
    with pytest.raises(ProviderFailure, match="invalid_account_or_asset_reference"):
        normalize_address(value)


@pytest.mark.parametrize(
    "endpoint",
    [
        "file:///tmp/fixture",
        "https://user:password@rpc.example",
        "https://rpc.example/#opaque",
        "http://",
        "https://rpc.example:bad",
        None,
    ],
)
def test_invalid_endpoints_are_sanitized(endpoint):
    with pytest.raises(ProviderFailure) as error:
        EvmRpcClient(endpoint)
    assert str(error.value) == "invalid_provider_endpoint"


async def test_closed_rpc_methods_and_erc20_params():
    calls = []

    def handler(request):
        data = json.loads(request.content)
        calls.append(data)
        result = "0x1" if data["method"] == "eth_chainId" else "0x" + "0" * 60 + "3039"
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": data["id"], "result": result})

    async with EvmBalanceProvider(
        "https://rpc.example.test", transport=httpx.MockTransport(handler)
    ) as provider:
        await provider.verify_chain_id(1)
        item = BalanceRequest("evm", "wallet", "chain", "asset", "UNIT", ADDRESS, TOKEN, 2)
        result = await provider.balance(item)
        assert result.atomic_units == 12345
        assert str(result.quantity) == "123.45"
        native = await provider._client.native_balance(ADDRESS)
        assert native == 12345
        with pytest.raises(ProviderFailure, match="provider_method_not_allowed"):
            await provider._client._call("unsupported_method", [])
    assert [c["method"] for c in calls] == ["eth_chainId", "eth_call", "eth_getBalance"]
    assert [c["id"] for c in calls] == [1, 2, 3]
    assert calls[1]["params"] == [{"to": TOKEN, "data": encode_balance_query(ADDRESS)}, "latest"]
    assert provider._client._client.is_closed


@pytest.mark.parametrize(
    "response",
    [
        {"jsonrpc": "2.0", "id": 1, "error": {"message": "opaque-endpoint"}},
        {"jsonrpc": "2.0", "id": 99, "result": "0x1"},
        {"jsonrpc": "2.0", "id": True, "result": "0x1"},
        {"id": 1, "result": "0x1"},
        [],
        {"jsonrpc": "2.0", "id": 1, "result": "not-hex"},
        {"jsonrpc": "2.0", "id": 1, "result": "0x1" + "0" * 32},
    ],
)
async def test_invalid_rpc_responses(response):
    async with EvmRpcClient(
        "https://rpc.example.test/opaque",
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json=response)),
    ) as client:
        with pytest.raises(ProviderFailure) as error:
            await client.native_balance(ADDRESS)
        assert "opaque" not in str(error.value)


@pytest.mark.parametrize(
    "status,body",
    [
        (302, b"opaque"),
        (500, b"opaque"),
        (200, b"not json"),
        (200, b"x" * (MAX_RESPONSE_BYTES + 1)),
    ],
)
async def test_http_failures_redirects_and_body_limit(status, body):
    calls = []

    def handler(request):
        calls.append(request.url)
        return httpx.Response(
            status, content=body, headers={"Location": "https://other.example.test"}
        )

    async with EvmRpcClient(
        "https://rpc.example.test", transport=httpx.MockTransport(handler)
    ) as client:
        with pytest.raises(ProviderFailure, match="provider_response_error"):
            await client.native_balance(ADDRESS)
    assert len(calls) == 1


async def test_network_failure_and_chain_mismatch():
    def handler(request):
        raise httpx.ConnectError("opaque-endpoint", request=request)

    async with EvmRpcClient(
        "https://rpc.example.test", transport=httpx.MockTransport(handler)
    ) as client:
        with pytest.raises(ProviderFailure, match="provider_network_error"):
            await client.chain_id()
    async with EvmBalanceProvider(
        "https://rpc.example.test",
        transport=httpx.MockTransport(
            lambda request: httpx.Response(200, json={"jsonrpc": "2.0", "id": 1, "result": "0x2"})
        ),
    ) as provider:
        with pytest.raises(ProviderFailure, match="chain_id_mismatch"):
            await provider.verify_chain_id(1)
