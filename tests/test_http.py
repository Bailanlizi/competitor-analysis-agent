"""Tests for infra/http.py (SPEC-2026-060 AC-1~4)."""

from __future__ import annotations

import httpx
import pytest
import respx

from infra.http import HttpClientError, fetch_with_retry


@pytest.mark.asyncio
async def test_ac1_network_timeout_retry_success():
    url = "https://example.com/retry-success"
    with respx.mock:
        route = respx.get(url).mock(
            side_effect=[
                httpx.ConnectTimeout("timeout"),
                httpx.ConnectTimeout("timeout"),
                httpx.Response(200, text="ok"),
            ]
        )
        async with httpx.AsyncClient() as client:
            resp = await fetch_with_retry(client, url)
        assert resp.status_code == 200
        assert route.call_count == 3


@pytest.mark.asyncio
async def test_ac2_network_timeout_all_fail():
    url = "https://example.com/retry-fail"
    with respx.mock:
        respx.get(url).mock(side_effect=httpx.ConnectTimeout("timeout"))
        async with httpx.AsyncClient() as client:
            with pytest.raises(httpx.ConnectTimeout):
                await fetch_with_retry(client, url)


@pytest.mark.asyncio
async def test_ac3_http_404_no_retry():
    url = "https://example.com/not-found"
    with respx.mock:
        route = respx.get(url).mock(return_value=httpx.Response(404))
        async with httpx.AsyncClient() as client:
            with pytest.raises(HttpClientError) as exc_info:
                await fetch_with_retry(client, url)
        assert exc_info.value.status_code == 404
        assert route.call_count == 1


@pytest.mark.asyncio
async def test_ac4_http_502_retry():
    url = "https://example.com/server-error"
    with respx.mock:
        route = respx.get(url).mock(
            side_effect=[
                httpx.Response(502),
                httpx.Response(200, text="ok"),
            ]
        )
        async with httpx.AsyncClient() as client:
            resp = await fetch_with_retry(client, url)
        assert resp.status_code == 200
        assert route.call_count == 2
