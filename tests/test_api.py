from unittest.mock import patch
from fastapi.testclient import TestClient

import sys, os
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app.main import app


client = TestClient(app)


def test_root_returns_html():
    """GET / returns 200 with HTML content."""
    with patch("app.main.NewsScraper.fetch_news", return_value=([], [], [])):
        response = client.get("/")
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert "Retail News Scout" in response.text


def test_root_with_date_param():
    """GET /?date=2025-10-25 passes the date and returns HTML."""
    with patch("app.main.NewsScraper.fetch_news", return_value=([], [], [])) as mock_fetch:
        response = client.get("/?date=2025-10-25")
    assert response.status_code == 200
    mock_fetch.assert_called_once()
    args = mock_fetch.call_args
    assert args[0][1] == "2025-10-25"


def test_root_with_companies_param():
    """GET /?companies=lawson&companies=aeon filters to selected companies."""
    with patch("app.main.NewsScraper.fetch_news", return_value=([], [], [])) as mock_fetch:
        response = client.get("/?companies=lawson&companies=aeon")
    assert response.status_code == 200
    mock_fetch.assert_called_once()
    args = mock_fetch.call_args
    assert set(args[0][0]) == {"lawson", "aeon"}


def test_root_contains_sidebar():
    """The response HTML includes the sidebar with company checkboxes."""
    with patch("app.main.NewsScraper.fetch_news", return_value=([], [], [])):
        response = client.get("/")
    assert "NEWS SCOUT" in response.text
    assert "SEARCH NEWS" in response.text


def test_news_items_rendered():
    """When fetch_news returns items, they appear in the page's JS payload."""
    fake_items = [
        {
            "company_name": "TestCo",
            "badge_color": "#000",
            "title": "Test News Title",
            "url": "https://example.com/news/1",
            "date": "2025-10-25",
            "is_link_only": False,
            "is_error": False,
        }
    ]
    with patch(
        "app.main.NewsScraper.fetch_news",
        return_value=(fake_items, ["log1"], ["TestCo"]),
    ):
        response = client.get("/?date=2025-10-25")
    assert response.status_code == 200
    assert "Test News Title" in response.text
