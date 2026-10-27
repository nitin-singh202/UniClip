import os
import pytest
from pathlib import Path
from web.config import Config, TestConfig, find_service_account_key


def test_firebase_api_key_loaded_from_config():
    """Verify Config exposes FIREBASE_API_KEY from environment or defaults cleanly."""
    # When instantiated or read, Config should have a string type
    assert isinstance(Config.FIREBASE_API_KEY, str)


def test_firebase_client_config_structure():
    """Verify get_firebase_client_config returns all expected public keys for browser SDK."""
    client_config = Config.get_firebase_client_config()
    assert isinstance(client_config, dict)
    expected_keys = {
        "apiKey",
        "authDomain",
        "projectId",
        "storageBucket",
        "messagingSenderId",
        "appId",
    }
    assert expected_keys.issubset(set(client_config.keys()))
    assert client_config["apiKey"] == Config.FIREBASE_API_KEY
    assert client_config["projectId"] == Config.FIREBASE_PROJECT_ID


def test_service_account_discovery_env_override(tmp_path, monkeypatch):
    """Verify FIREBASE_SERVICE_ACCOUNT_KEY env var overrides filesystem search."""
    fake_key = tmp_path / "mock-service-account.json"
    fake_key.write_text('{"type": "service_account"}', encoding="utf-8")

    monkeypatch.setenv("FIREBASE_SERVICE_ACCOUNT_KEY", str(fake_key))
    discovered = find_service_account_key()
    assert discovered == str(fake_key.resolve())


def test_production_config_validation_rejects_insecure_secret():
    """Verify Config.validate raises error in production when default insecure SECRET_KEY is used."""
    class ProdInsecureConfig(Config):
        FLASK_ENV = "production"
        SECRET_KEY = "dev-insecure-key-change-in-production"
        DEV_MOCK_AUTH = False
        FIREBASE_API_KEY = "AIzaSyDummyKeyForProductionValidationCheck"

    with pytest.raises(ValueError, match="Insecure or missing SECRET_KEY"):
        ProdInsecureConfig.validate()


def test_production_config_validation_rejects_missing_secret():
    """Verify Config.validate raises error in production when SECRET_KEY is empty."""
    class ProdMissingSecretConfig(Config):
        FLASK_ENV = "production"
        SECRET_KEY = ""
        DEV_MOCK_AUTH = False
        FIREBASE_API_KEY = "AIzaSyDummyKeyForProductionValidationCheck"

    with pytest.raises(ValueError, match="Insecure or missing SECRET_KEY"):
        ProdMissingSecretConfig.validate()


def test_production_config_validation_rejects_dev_mock_auth():
    """Verify Config.validate raises error in production when DEV_MOCK_AUTH is enabled."""
    class ProdMockAuthConfig(Config):
        FLASK_ENV = "production"
        SECRET_KEY = "secure-random-32-byte-hex-secret-key"
        DEV_MOCK_AUTH = True
        FIREBASE_API_KEY = "AIzaSyDummyKeyForProductionValidationCheck"

    with pytest.raises(ValueError, match="DEV_MOCK_AUTH cannot be enabled in production"):
        ProdMockAuthConfig.validate()


def test_production_config_validation_requires_firebase_api_key():
    """Verify Config.validate raises error in production when FIREBASE_API_KEY is missing."""
    class ProdMissingKeyConfig(Config):
        FLASK_ENV = "production"
        SECRET_KEY = "secure-random-32-byte-hex-secret-key"
        DEV_MOCK_AUTH = False
        FIREBASE_API_KEY = ""

    with pytest.raises(ValueError, match="FIREBASE_API_KEY must be configured for production"):
        ProdMissingKeyConfig.validate()


def test_production_config_validation_passes_when_configured():
    """Verify Config.validate passes in production when all credentials are appropriately set."""
    class ProdValidConfig(Config):
        FLASK_ENV = "production"
        SECRET_KEY = "secure-random-32-byte-hex-secret-key"
        DEV_MOCK_AUTH = False
        FIREBASE_API_KEY = "AIzaSyDummyKeyForProductionValidationCheck"

    # Should not raise
    ProdValidConfig.validate()


def test_development_config_preserves_mock_auth_and_dev_defaults():
    """Verify Config.validate passes in development mode with dev defaults and mock auth."""
    class DevConfig(Config):
        FLASK_ENV = "development"
        SECRET_KEY = "dev-insecure-key-change-in-production"
        DEV_MOCK_AUTH = True
        FIREBASE_API_KEY = ""

    # Should not raise
    DevConfig.validate()


def test_test_config_validation_passes():
    """Verify TestConfig passes validation and does not require production credentials."""
    TestConfig.validate()
    assert TestConfig.TESTING is True
    assert TestConfig.SECRET_KEY == "test-secret-key-testing-only"
    assert TestConfig.DEV_MOCK_AUTH is True
