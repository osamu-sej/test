"""v1.6.0: 取得失敗への多層フォールバックのテスト。

1. 兄弟要素パターン: 日付とタイトルリンクが別々の要素として並ぶレイアウト
   (経済産業省などの省庁サイトに多い)からの抽出
2. フィード(RSS/Atom)フォールバック: HTML から0件のとき、ページが宣言する
   フィードや設定済み rss_url から自動取得する自己修復
"""
from unittest.mock import patch

import requests

from app import scraper
from app.scraper import NewsScraper

# 経産省型: 日付だけの <p> の隣に、タイトルリンクの <p> が並ぶ
METI_LIKE_HTML = """
<html><body>
<div class="press-list">
  <div class="row">
    <p class="date">2026年7月6日</p>
    <p class="title"><a href="/press/2026/07/a.html">キャッシュレス決済の実態調査結果を公表します</a></p>
  </div>
  <div class="row">
    <p class="date">2026年7月5日</p>
    <p class="link"><a href="/list.html">一覧を見る</a></p>
    <p class="title"><a href="/press/2026/07/b.html">物流効率化に向けた検討会を開催します</a></p>
  </div>
  <div class="row">
    <p class="date">2025年1月1日</p>
    <p class="title"><a href="/press/old.html">範囲外の古い発表</a></p>
  </div>
</div>
</body></html>
"""

# HTML からは何も抽出できないが、<head> で RSS を宣言しているページ
RSS_DISCOVERY_HTML = """
<html><head>
<link rel="alternate" type="application/rss+xml" href="/news/feed.xml">
</head><body><p>JavaScript を有効にしてください。</p></body></html>
"""

RSS_XML = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel>
  <title>News</title>
  <item>
    <title>新しい支援制度を開始します</title>
    <link>https://example.gov/news/1.html</link>
    <pubDate>Mon, 06 Jul 2026 10:00:00 +0900</pubDate>
  </item>
  <item>
    <title>期間外の古いお知らせ</title>
    <link>https://example.gov/news/old.html</link>
    <pubDate>Wed, 01 Jan 2025 10:00:00 +0900</pubDate>
  </item>
</channel></rss>
"""

ATOM_DISCOVERY_HTML = """
<html><head>
<link rel="alternate" type="application/atom+xml" href="https://example.gov/atom.xml">
</head><body><p>お知らせはありません(動的描画)。</p></body></html>
"""

ATOM_XML = """<?xml version="1.0" encoding="utf-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <title>News Feed</title>
  <entry>
    <title>制度改正に関する説明会のご案内</title>
    <link href="https://example.gov/news/2.html"/>
    <updated>2026-07-06T09:00:00+09:00</updated>
  </entry>
</feed>
"""


class FakeResponse:
    def __init__(self, status_code, text):
        self.status_code = status_code
        self.text = text
        self.content = text.encode("utf-8")
        self.encoding = "utf-8"
        self.apparent_encoding = "utf-8"


def _fake_get_factory(pages):
    def fake_get(self, url, timeout=None, **kwargs):
        for key, html in pages.items():
            if key in url:
                return FakeResponse(200, html)
        return FakeResponse(404, "")
    return fake_get


TEST_COMPANY = {
    "id": "testgov", "name": "テスト省", "category": "行政・団体",
    "url": "https://example.gov/press/", "scraper_type": "auto",
    "badge_color": "#123456", "date_format": "%Y年%m月%d日",
}


def _fetch(monkeypatch, pages, company=None, start="2026-07-01", end="2026-07-07"):
    monkeypatch.setattr(requests.Session, "get", _fake_get_factory(pages))
    with patch.object(scraper, "COMPANIES", [company or TEST_COMPANY]):
        return NewsScraper().fetch_news([(company or TEST_COMPANY)["id"]], start, end)


def test_sibling_layout_extracted(monkeypatch):
    """日付とタイトルリンクが別要素で並ぶレイアウト(経産省型)から抽出できる。"""
    items, logs, checked = _fetch(monkeypatch, {"/press/": METI_LIKE_HTML})
    titles = [i["title"] for i in items]
    assert "キャッシュレス決済の実態調査結果を公表します" in titles
    # 「一覧を見る」のような案内リンクは飛ばし、その先のタイトルを拾う
    assert "物流効率化に向けた検討会を開催します" in titles
    assert not any("一覧を見る" in t for t in titles)
    assert not any("範囲外" in t for t in titles)


def test_rss_fallback_when_html_yields_nothing(monkeypatch):
    """HTML から0件でも、<head> 宣言の RSS を自動発見して取得できる。"""
    items, logs, checked = _fetch(monkeypatch, {
        "/press/": RSS_DISCOVERY_HTML,
        "/news/feed.xml": RSS_XML,
    })
    titles = [i["title"] for i in items]
    assert titles == ["新しい支援制度を開始します"]
    assert items[0]["url"] == "https://example.gov/news/1.html"
    assert items[0]["date"] == "2026-07-06"
    assert any("Feed fallback" in l for l in logs)


def test_atom_fallback(monkeypatch):
    """Atom フィードでも同様に取得できる。"""
    items, logs, checked = _fetch(monkeypatch, {
        "/press/": ATOM_DISCOVERY_HTML,
        "/atom.xml": ATOM_XML,
    })
    assert [i["title"] for i in items] == ["制度改正に関する説明会のご案内"]
    assert items[0]["date"] == "2026-07-06"


def test_rss_url_config_takes_priority(monkeypatch):
    """companies.py に rss_url を設定すると、head 宣言がなくてもフィードを読む。"""
    company = {**TEST_COMPANY, "rss_url": "https://example.gov/custom-feed.xml"}
    items, logs, checked = _fetch(monkeypatch, {
        "/press/": "<html><body>お知らせなし</body></html>",
        "/custom-feed.xml": RSS_XML,
    }, company=company)
    assert [i["title"] for i in items] == ["新しい支援制度を開始します"]


def test_feed_errors_never_crash(monkeypatch):
    """フィードが壊れた XML でも例外にせず、静かに0件として扱う。"""
    items, logs, checked = _fetch(monkeypatch, {
        "/press/": RSS_DISCOVERY_HTML,
        "/news/feed.xml": "this is not xml <<<",
    })
    assert items == []
    assert any("Feed error" in l for l in logs)