"""Streamlit 중첩 이벤트 루프 패치 검증."""

import asyncio

import nest_asyncio


def test_nested_asyncio_run_succeeds_after_apply():
    nest_asyncio.apply()

    async def inner():
        return 42

    async def outer():
        return asyncio.run(inner())

    assert asyncio.run(outer()) == 42
