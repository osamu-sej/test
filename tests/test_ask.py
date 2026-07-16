"""AI Q&A (/ask) エンドポイントと v1.6.0 UI 要素のテスト。Claude API はモックする。"""
from unittest.mock import patch

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


def _ask(question="いちご関連の動きは?", **kwargs):
    body = {
        "question": question,
        "start_date": "2025-10-25",
        "end_date": "2025-10-25",
        "companies": ["lawson"],
    }
    body.update(kwargs)
    return client.post("/ask", json=body)


def test_ask_disabled_without_api_key(monkeypatch):
    _clear_ai_env(monkeypatch)
    res = _ask()
    assert res.status_code == 200
    assert res.json()["enabled"] is False


def test_ask_empty_question_rejected(monkeypatch):
    _enable_ai(monkeypatch)
    res = _ask(question="   ")
    assert res.status_code == 400
    assert "質問を入力" in res.json()["error"]


def test_ask_too_long_question_rejected(monkeypatch):
    _enable_ai(monkeypatch)
    res = _ask(question="あ" * 501)
    assert res.status_code == 400
    assert "以内" in res.json()["error"]


def test_ask_no_items(monkeypatch):
    _enable_ai(monkeypatch)
    res = _ask()
    body = res.json()
    assert res.status_code == 200
    assert body["enabled"] is True
    assert body["answer"] is None
    assert "収集" in body["message"]


def test_ask_answered_and_cached(monkeypatch):
    _enable_ai(monkeypatch)
    _seed_news()
    calls = []

    def fake_answer(question, items, start, end):
        calls.append((question, len(items), start, end))
        return "[2025-10-25] ローソン: いちごフェア開催のお知らせ が該当します。"

    monkeypatch.setattr(ai, "answer_question", fake_answer)

    res1 = _ask()
    body1 = res1.json()
    assert res1.status_code == 200
    assert "いちごフェア" in body1["answer"]
    assert body1["cached"] is False
    assert body1["item_count"] == 1
    assert calls == [("いちご関連の動きは?", 1, "2025-10-25", "2025-10-25")]

    # 同一質問・同一条件の2回目は API を呼ばずキャッシュから返す
    res2 = _ask()
    assert res2.json()["cached"] is True
    assert len(calls) == 1

    # 質問が変わればキャッシュは使われない
    res3 = _ask(question="別の質問です")
    assert res3.json()["cached"] is False
    assert len(calls) == 2


def test_ask_api_error_returns_502(monkeypatch):
    _enable_ai(monkeypatch)
    _seed_news()

    def fail_answer(question, items, start, end):
        raise ai.AIDigestError("Claude API のレート制限に達しました。")

    monkeypatch.setattr(ai, "answer_question", fail_answer)
    res = _ask()
    assert res.status_code == 502
    assert "レート制限" in res.json()["error"]


def test_ui_elements_present(monkeypatch):
    """v1.6.0 の UI 要素(並び替え・未読フィルタ・AI タブ)がページに含まれる。"""
    _enable_ai(monkeypatch)
    with patch("app.main.NewsScraper.fetch_news", return_value=([], [], [])):
        res = client.get("/?companies=lawson")
    assert res.status_code == 200
    assert 'id="sortSelect"' in res.text
    assert 'id="btn-unread"' in res.text
    assert 'id="scroll-top-btn"' in res.text
    assert 'id="tab-ask"' in res.text
    assert 'id="ask-input"' in res.text
    assert "AI アシスタント" in res.text
    # CSV の「業態」列用の企業カテゴリマップが埋め込まれている
    assert "window.COMPANY_CATEGORIES" in res.text
    assert "ディスカウント" in res.text


def test_ai_ui_hidden_without_api_key(monkeypatch):
    """API キー未設定でも画面は表示され、AI ボタンだけ出ない。"""
    _clear_ai_env(monkeypatch)
    with patch("app.main.NewsScraper.fetch_news", return_value=([], [], [])):
        res = client.get("/?companies=lawson")
    assert res.status_code == 200
    assert "AI アシスタント" not in res.text
