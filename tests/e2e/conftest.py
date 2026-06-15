"""E2E test configuration."""
import os
import pytest
from cryptography.fernet import Fernet

# Ensure a valid Fernet key is available before client.config is imported.
if not os.getenv("ENCRYPTION_KEY"):
    os.environ["ENCRYPTION_KEY"] = Fernet.generate_key().decode()


def pytest_addoption(parser):
    parser.addoption(
        "--live-browser",
        action="store_true",
        default=False,
        help="Run tests that require a real browser and bridge-server",
    )


def pytest_configure(config):
    config.addinivalue_line(
        "markers", "live_browser: marks tests that require a real browser and bridge-server"
    )


def pytest_collection_modifyitems(config, items):
    if not config.getoption("--live-browser"):
        skip_live = pytest.mark.skip(reason="Use --live-browser to run live browser tests")
        for item in items:
            if "live_browser" in item.keywords:
                item.add_marker(skip_live)
