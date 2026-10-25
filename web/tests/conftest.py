import pytest
from web.app import create_app
from web.config import TestConfig
from web.services import ClipboardService, AuthService


@pytest.fixture
def app():
    """Create and configure a testing Flask application instance."""
    app = create_app(TestConfig)
    yield app
    # Clean up test store after each test
    ClipboardService.reset_store()


@pytest.fixture
def client(app):
    """A test client for the app."""
    return app.test_client()


@pytest.fixture
def auth_client(app, client):
    """A test client with an established authenticated session for 'user_alice'."""
    with client.session_transaction() as sess:
        sess["user"] = {
            "uid": "user_alice",
            "email": "alice@example.com",
            "name": "Alice Smith",
        }
        sess["_csrf_token"] = "test-csrf-token-alice"
    return client


@pytest.fixture
def bob_client(app, client):
    """A test client with an established authenticated session for 'user_bob'."""
    with client.session_transaction() as sess:
        sess["user"] = {
            "uid": "user_bob",
            "email": "bob@example.com",
            "name": "Bob Jones",
        }
        sess["_csrf_token"] = "test-csrf-token-bob"
    return client
