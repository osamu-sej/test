"""AI ダイジェスト (/digest) エンドポイントのテスト。Claude API はモックする。"""
from fastapi.testclient import TestClient

from app import ai, storage
from app.main import app

client = TestClient(app)


def _clear_ai_env(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_AUTH_TOKEN", raising=False)


def _enable_ai(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-dummy")


def _seed_news():
    storage.save_items([{
        "company_id": "lawson",
        "company_name": "ローソン",
        "badge_color": "#0068b7",
        "title": "いちごフェア開催のお知らせ",
        "url": "https://example.com/n/1",
        "date": "2025-10-25",
    }])


def test_digest_disabled_without_api_key(monkeypatch):
    _clear_ai_env(monkeypatch)
    res = client.get("/digest?start_date=2025-10-25&end_date=2025-10-25")
    assert res.status_code == 200
    assert res.json()["enabled"] is False


def test_digest_no_items(monkeypatch):
    _enable_ai(monkeypatch)
    res = client.get("/digest?start_date=2025-10-25&end_date=2025-10-25")
    body = res.json()
    assert body["enabled"] is True
    assert body["digest"] is None
    assert "収集" in body["message"]


def test_digest_generated_and_cached(monkeypatch):
    _enable_ai(monkeypatch)
    _seed_news()
    calls = []

    def fake_generate(items, start, end):
        calls.append((len(items), start, end))
        return "【本日のハイライト】\n・テストダイジェスト"

    monkeypatch.setattr(ai, "generate_digest", fake_generate)

    res1 = client.get("/digest?start_date=2025-10-25&end_date=2025-10-25&companies=lawson")
    body1 = res1.json()
    assert res1.status_code == 200
    assert body1["digest"].startswith("【本日のハイライト】")
    assert body1["cached"] is False
    assert body1["item_count"] == 1
    assert calls == [(1, "2025-10-25", "2025-10-25")]

    # 2回目は API を呼ばずキャッシュから返す
    res2 = client.get("/digest?start_date=2025-10-25&end_date=2025-10-25&companies=lawson")
    assert res2.json()["cached"] is True
    assert len(calls) == 1


def test_digest_api_error_returns_502(monkeypatch):
    _enable_ai(monkeypatch)
    _seed_news()

    def fail_generate(items, start, end):
        raise ai.AIDigestError("Claude API のレート制限に達しました。")

    monkeypatch.setattr(ai, "generate_digest", fail_generate)
    res = client.get("/digest?start_date=2025-10-25&end_date=2025-10-25&companies=lawson")
    assert res.status_code == 502
    assert "レート制限" in res.json()["error"]
