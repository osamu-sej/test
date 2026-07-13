"""v1.6.1: メモリ超過対策のテスト。

- バッチ取得: 同時に取得・保持するページ数が FETCH_MAX_WORKERS を超えない
- 巨大ページの切り詰め: 上限を超える HTML はメモリに載せきらない
- スケジューラ既定値: 12時間おき
- env_int: 不正な環境変数値でアプリが落ちない
"""
import threading
import time
from unittest.mock import patch

import requests

from app import scheduler, scraper
from app.envutil import env_int
from app.scraper import MAX_HTML_CHARS, NewsScraper


class FakeResponse:
    def __init__(self, status_code, text):
        self.status_code = status_code
        self.text = text
        self.content = text.encode("utf-8")
        self.encoding = "utf-8"
        self.apparent_encoding = "utf-8"


def _make_companies(n):
    return [
        {
            "id": f"co{i}", "name": f"会社{i}", "category": "テスト",
            "url": f"https://fake.example/co{i}", "scraper_type": "auto",
            "badge_color": "#111111", "date_format": "%Y.%m.%d",
        }
        for i in range(n)
    ]


def test_batched_fetch_limits_concurrency(monkeypatch):
    """12社を取得しても、同時に接続する数は FETCH_MAX_WORKERS(既定5)以下。"""
    companies = _make_companies(12)
    lock = threading.Lock()
    state = {"current": 0, "max": 0}

    def fake_get(self, url, timeout=None, **kwargs):
        with lock:
            state["current"] += 1
            state["max"] = max(state["max"], state["current"])
        time.sleep(0.02)
        with lock:
            state["current"] -= 1
        i = url.rsplit("co", 1)[-1]
        return FakeResponse(200, f"""
            <html><body><ul>
              <li>2026.07.06 <a href="/news/{i}.html">会社{i}のお知らせタイトルです</a></li>
            </ul></body></html>
        """)

    monkeypatch.setattr(requests.Session, "get", fake_get)
    with patch.object(scraper, "COMPANIES", companies):
        items, logs, checked = NewsScraper().fetch_news(
            [c["id"] for c in companies], "2026-07-01", "2026-07-07"
        )

    assert state["max"] <= scraper.FETCH_MAX_WORKERS
    # 全社ぶん取得できており、順序も選択順のまま
    assert checked == [c["name"] for c in companies]
    assert [i["title"] for i in items] == [f"会社{i}のお知らせタイトルです" for i in range(12)]


def test_large_page_truncated(monkeypatch):
    """上限を超える巨大ページは切り詰めて解析する(上限内の記事は取得される)。"""
    company = _make_companies(1)[0]
    early_item = '<li>2026.07.06 <a href="/a.html">上限より前にある記事タイトル</a></li>'
    late_item = '<li>2026.07.06 <a href="/b.html">上限より後ろにある記事タイトル</a></li>'
    huge = "<html><body><ul>" + early_item + ("<!-- padding -->" * (MAX_HTML_CHARS // 16)) + late_item

    def fake_get(self, url, timeout=None, **kwargs):
        return FakeResponse(200, huge)

    monkeypatch.setattr(requests.Session, "get", fake_get)
    with patch.object(scraper, "COMPANIES", [company]):
        items, logs, checked = NewsScraper().fetch_news([company["id"]], "2026-07-01", "2026-07-07")

    titles = [i["title"] for i in items]
    assert "上限より前にある記事タイトル" in titles
    assert "上限より後ろにある記事タイトル" not in titles
    assert any("Truncated" in l for l in logs)


def _make_streaming_response(payload: bytes):
    """実際の requests のストリーミングレスポンスを模したオブジェクトを作る。"""
    import io
    import urllib3

    r = requests.Response()
    r.status_code = 200
    r.raw = urllib3.HTTPResponse(body=io.BytesIO(payload), preload_content=False, status=200)
    return r


def test_cap_response_body_stops_download_at_limit():
    """上限を超える本文はダウンロード段階で読み止められ、全文はメモリに載らない
    (Codex レビュー起因の回帰テスト: 全文取得後の切り詰めでは手遅れ)。"""
    payload = b"a" * (scraper.MAX_FETCH_BYTES + 500_000)
    r = _make_streaming_response(payload)
    NewsScraper._cap_response_body(r)
    assert len(r.content) < len(payload)
    assert len(r.content) <= scraper.MAX_FETCH_BYTES + 65536  # 最終チャンクぶんの余裕
    assert r._news_truncated is True


def test_cap_response_body_keeps_small_body_intact():
    r = _make_streaming_response(b"<html><body>hello</body></html>")
    NewsScraper._cap_response_body(r)
    assert r.content == b"<html><body>hello</body></html>"
    assert r.text.startswith("<html>")
    assert r._news_truncated is False


def test_cap_response_body_tolerates_non_streaming_objects():
    """iter_content を持たないオブジェクト(テスト用ダミー等)はそのまま通す。"""
    fake = FakeResponse(200, "<html></html>")
    NewsScraper._cap_response_body(fake)
    assert fake.text == "<html></html>"


def test_scheduler_default_interval_is_12_hours():
    assert scheduler.DEFAULT_INTERVAL_SECONDS == 43200


def test_env_int_safe_parsing(monkeypatch):
    monkeypatch.delenv("X_TEST_ENV_INT", raising=False)
    assert env_int("X_TEST_ENV_INT", 7) == 7
    monkeypatch.setenv("X_TEST_ENV_INT", "12")
    assert env_int("X_TEST_ENV_INT", 7) == 12
    monkeypatch.setenv("X_TEST_ENV_INT", "abc")
    assert env_int("X_TEST_ENV_INT", 7) == 7
    monkeypatch.setenv("X_TEST_ENV_INT", "")
    assert env_int("X_TEST_ENV_INT", 7) == 7
    monkeypatch.setenv("X_TEST_ENV_INT", "-5")
    assert env_int("X_TEST_ENV_INT", 7, minimum=1) == 1
