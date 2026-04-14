"""Shared fixtures for all tests."""

import asyncio
import os
import tempfile

import pytest
import pytest_asyncio

# Use a temporary test database file
_test_db = tempfile.mktemp(suffix=".db")
os.environ["DB_PATH"] = _test_db

from db.database import init_db  # noqa: E402
from db.auth import create_user, authenticate_user  # noqa: E402
from fastmcp import Client  # noqa: E402
from tools.registry import mcp  # noqa: E402


@pytest.fixture(scope="session")
def event_loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()
    # Cleanup temp DB
    try:
        os.unlink(_test_db)
    except FileNotFoundError:
        pass


@pytest_asyncio.fixture(scope="session", autouse=True)
async def db():
    """Initialize the test database once for all tests."""
    await init_db()


@pytest_asyncio.fixture
async def user(db):
    """Create a test user and return their ID."""
    try:
        u = await create_user("test@openpa.dev", "testpass", "Test User")
    except ValueError:
        u = await authenticate_user("test@openpa.dev", "testpass")
    return u["id"]


@pytest_asyncio.fixture
async def mcp_client():
    """Create an MCP client connected to the tool server."""
    async with Client(mcp) as client:
        yield client
