"""Pytest configuration."""
import os
from cryptography.fernet import Fernet

# Ensure tests have a valid Fernet encryption key available before
# client.config is imported.
if not os.getenv("ENCRYPTION_KEY"):
    os.environ["ENCRYPTION_KEY"] = Fernet.generate_key().decode()
