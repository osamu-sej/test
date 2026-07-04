"""v1.5.0 実務UX: 情報源の新着停止警告のテスト。"""
from datetime import datetime, timedelta
from unittest.mock import patch

from fastapi.testclient import TestClient

from app import storage
from app.main import app

client = TestClient(app)


def _seed(company_id, name, date_str, url):
    storage.save_items([{
        "company_id": company_id,
        "company_name": name,
        "badge_color": "#123456",
        "title": "テストニュース",
        "url": url,
        "date": date_str,
    }])


def _days_ago(n):
    return (datetime.now() - timedelta(days=n)).strftime("%Y-%m-%d")


def test_last_item_dates():
    _seed("lawson", "ローソン", "2025-10-01", "https://example.com/a")
    _seed("lawson", "ローソン", "2025-10-20", "https://example.com/b")
    assert storage.last_item_dates(["lawson"]) == {"lawson": "2025-10-20"}
    assert storage.last_item_dates(["famima"]) == {}


def test_stale_source_warning_shown():
    """直近60日以内に実績があり7日超新着なし → 警告バナー表示。"""
    _seed("lawson", "ローソン", _days_ago(20), "https://example.com/stale")
    with patch("app.main.NewsScraper.fetch_news", return_value=([], [], [])):
        res = client.get("/?companies=lawson")
    assert "しばらく新着を取得できていない情報源" in res.text
    assert "ローソン(20日)" in res.text


def test_no_warning_for_recent_or_ancient():
    """直近の実績あり(2日前)や、もともと更新が止まっている(100日前)は警告しない。"""
    _seed("lawson", "ローソン", _days_ago(2), "https://example.com/recent")
    _seed("aeon", "イオン", _days_ago(100), "https://example.com/ancient")
    with patch("app.main.NewsScraper.fetch_news", return_value=([], [], [])):
        res = client.get("/?companies=lawson&companies=aeon")
    assert "しばらく新着を取得できていない情報源" not in res.text
