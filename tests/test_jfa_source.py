"""jfa_fc(日本フランチャイズチェーン協会)を force_link から auto に修正したことの回帰テスト。

実サイトのトップページは dt/dd 形式の日付付きお知らせ一覧を持つため
(2026.07.01 のような日付 + リンク付きタイトル)、汎用スクレイパーで
抽出できることを、同じ構造を模したフィクスチャで確認する。
"""
from unittest.mock import patch

import requests

from app.companies import COMPANIES
from app.scraper import NewsScraper

JFA_FIXTURE_HTML = """
<html><body>
<div class="whats-new">
  <dl>
    <dt>2026.07.01</dt>
    <dd><a href="/news/20260701.html">機関誌「フランチャイズエイジ」最新7月号目次</a></dd>
    <dt>2026.06.11</dt>
    <dd><a href="/news/202606011.html">FRANCHISING &amp; LICENSING ASIA(FLAsia)2026 出展者募集のご案内</a></dd>
    <dt>2025.09.01</dt>
    <dd><a href="/news/old.html">範囲外の古いお知らせ</a></dd>
  </dl>
</div>
</body></html>
"""


class FakeResponse:
    def __init__(self, status_code, text):
        self.status_code = status_code
        self.text = text
        self.encoding = "utf-8"
        self.apparent_encoding = "utf-8"


def test_jfa_fc_is_auto_scraped_not_force_link():
    company = next(c for c in COMPANIES if c["id"] == "jfa_fc")
    assert company["scraper_type"] == "auto", (
        "jfa_fc は実際にはニュース一覧を持つサイトのため、"
        "リンクのみ表示(force_link)ではなく通常抽出(auto)であるべき"
    )


def test_jfa_fc_generic_scraper_extracts_titles(monkeypatch):
    def fake_get(self, url, timeout=None, **kwargs):
        return FakeResponse(200, JFA_FIXTURE_HTML)

    monkeypatch.setattr(requests.Session, "get", fake_get)
    items, logs, checked = NewsScraper().fetch_news(["jfa_fc"], "2026-06-01", "2026-07-01")

    assert checked == ["日本フランチャイズチェーン協会"]
    titles = [i["title"] for i in items]
    assert any("フランチャイズエイジ" in t for t in titles)
    assert any("FLAsia" in t for t in titles)
    # 期間外の記事は含まれない
    assert not any("範囲外" in t for t in titles)
    # force_link 特有のリンクのみ表示にはなっていない
    assert all(not i["is_link_only"] for i in items)
