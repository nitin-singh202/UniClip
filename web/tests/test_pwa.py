"""
Tests for Progressive Web App (PWA) components in UniClip.
Verifies manifest metadata, service worker headers, privacy boundaries,
and responsive template tags.
"""
import json
import pytest
from web.app import create_app
from web.config import TestConfig


@pytest.fixture
def client():
    app = create_app(TestConfig)
    with app.test_client() as test_client:
        yield test_client


def test_manifest_webmanifest_endpoint(client):
    """Verify /manifest.webmanifest serves valid PWA manifest with correct MIME type."""
    response = client.get("/manifest.webmanifest")
    assert response.status_code == 200
    assert "application/manifest+json" in response.headers.get("Content-Type", "")

    data = json.loads(response.data)
    assert data.get("name") == "UniClip"
    assert data.get("short_name") == "UniClip"
    assert data.get("start_url") == "/dashboard"
    assert data.get("scope") == "/"
    assert data.get("display") == "standalone"
    assert data.get("theme_color") == "#0b0f17"
    assert data.get("background_color") == "#0b0f17"

    icons = data.get("icons", [])
    assert len(icons) >= 2
    sizes = [icon.get("sizes") for icon in icons]
    assert "192x192" in sizes
    assert "512x512" in sizes


def test_service_worker_endpoint(client):
    """Verify /sw.js is served with proper MIME type and root scope authority."""
    for path in ("/sw.js", "/service-worker.js"):
        response = client.get(path)
        assert response.status_code == 200
        assert "application/javascript" in response.headers.get("Content-Type", "")
        assert response.headers.get("Service-Worker-Allowed") == "/"

        content = response.data.decode("utf-8")
        # Ensure security constraint: Service worker must strictly exclude /api/ routes
        assert 'url.pathname.startsWith("/api/")' in content
        # Ensure no credential caching
        assert "password" not in content.lower()
        assert "idtoken" not in content.lower()


def test_offline_fallback_page(client):
    """Verify /offline fallback page shell is accessible without authentication."""
    response = client.get("/offline")
    assert response.status_code == 200
    html = response.data.decode("utf-8")
    assert "offline" in html.lower()
    assert "Retry Connection" in html or "retry" in html.lower()


def test_pwa_head_meta_tags_in_templates(client):
    """Verify HTML pages include PWA manifest link and theme-color meta tags."""
    response = client.get("/login")
    assert response.status_code == 200
    html = response.data.decode("utf-8")

    assert 'rel="manifest"' in html
    assert 'name="theme-color"' in html
    assert "#0b0f17" in html
    assert 'name="mobile-web-app-capable"' in html
    assert 'name="apple-mobile-web-app-capable"' in html


def test_static_pwa_icons_accessible(client):
    """Verify standard and maskable PWA icons are served with HTTP 200."""
    for icon_name in ("icon-192.png", "icon-512.png", "icon-maskable-192.png", "icon-maskable-512.png"):
        response = client.get(f"/static/icons/{icon_name}")
        assert response.status_code == 200
        assert "image/png" in response.headers.get("Content-Type", "")
