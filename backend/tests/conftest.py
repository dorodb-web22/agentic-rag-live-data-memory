"""Shared pytest configuration for backend tests.

Provides a lightweight fallback runner for `async def` tests marked with
`@pytest.mark.asyncio` in environments (such as CI) where `pytest-asyncio`
is not pre-installed.
"""
from __future__ import annotations

import asyncio
import inspect
from typing import Any

import pytest


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line("markers", "asyncio: run async test function inside an event loop")


@pytest.hookimpl(tryfirst=True)
def pytest_pyfunc_call(pyfuncitem: pytest.Function) -> bool | None:
    # Defer to pytest-asyncio if active on this session
    if pyfuncitem.config.pluginmanager.has_plugin("asyncio"):
        return None

    testfunction = pyfuncitem.obj
    if not inspect.iscoroutinefunction(testfunction):
        return None

    funcargs: dict[str, Any] = pyfuncitem.funcargs
    sig = inspect.signature(testfunction)
    kwargs = {name: funcargs[name] for name in sig.parameters if name in funcargs}
    asyncio.run(testfunction(**kwargs))
    return True
