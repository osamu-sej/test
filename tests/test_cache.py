"""サーバー側キャッシュ(storage / service)のテスト。"""
from app import service, storage
from app.companies import COMPANIES
from app.scraper import NewsScraper


def _make_item(name, title="ニュースタイトルテスト", url="https://example.com/n/1", date="2025-10-25"):
    return {
        "company_name": name,
        "badge_color": "#123456",
        "title": title,
        "url": url,
        "date": date,
        "is_link_only": False,
        "is_error": False,
    }


def _company(cid):
    return next(c for c in COMPANIES if c["id"] == cid)


def test_storage_roundtrip():
    storage.save_items([{**_make_item("ローソン"), "company_id": "lawson"}])
    items = storage.get_items("lawson", "2025-10-25", "2025-10-26")
    assert len(items) == 1
    assert items[0]["title"] == "ニュースタイトルテスト"
    assert items[0]["is_link_only"] is False
    # 同一 URL+日付は初出優先で重複しない
    storage.save_items([{**_make_item("ローソン", title="別タイトル"), "company_id": "lawson"}])
    assert len(storage.get_items("lawson", "2025-10-25", "2025-10-26")) == 1


def test_second_request_served_from_cache(monkeypatch):
    calls = []
    lawson = _company("lawson")["name"]

    def fake_fetch(self, ids, start, end):
        calls.append(list(ids))
        self.last_status = {cid: ("ok", 200) for cid in ids}
        return [_make_item(lawson)], ["scraped"], [lawson]

    monkeypatch.setattr(NewsScraper, "fetch_news", fake_fetch)

    items1, logs1, checked1, _ = service.get_news(["lawson"], "2025-10-25", "2025-10-25")
    assert len(calls) == 1
    assert [i["title"] for i in items1] == ["ニュースタイトルテスト"]

    # 2回目: 過去日はキャッシュ内なので再スクレイピングされない
    items2, logs2, checked2, last_collected = service.get_news(["lawson"], "2025-10-25", "2025-10-25")
    assert len(calls) == 1, "cached request must not re-scrape"
    assert [i["title"] for i in items2] == ["ニュースタイトルテスト"]
    assert checked2 == [lawson]
    assert last_collected is not None
    assert any("cache hit" in l for l in logs2)

    # force=True なら必ず再スクレイピング
    service.get_news(["lawson"], "2025-10-25", "2025-10-25", force=True)
    assert len(calls) == 2


def test_cached_403_reproduces_fallback_link(monkeypatch):
    aeon = _company("aeon")

    def fake_fetch(self, ids, start, end):
        self.last_status = {cid: ("403", 403) for cid in ids}
        return [self._fallback_item(aeon, start, 403)], ["403"], [aeon["name"]]

    monkeypatch.setattr(NewsScraper, "fetch_news", fake_fetch)
    items1, _, _, _ = service.get_news(["aeon"], "2025-10-25", "2025-10-25")
    assert items1[0]["is_link_only"] is True

    def fail_fetch(self, ids, start, end):
        raise AssertionError("must not scrape when 403 is cached")

    monkeypatch.setattr(NewsScraper, "fetch_news", fail_fetch)
    items2, logs2, _, _ = service.get_news(["aeon"], "2025-10-25", "2025-10-25")
    assert len(items2) == 1
    assert items2[0]["is_link_only"] is True
    assert items2[0]["url"] == aeon["url"]


def test_partial_scrape_only_stale_companies(monkeypatch):
    """キャッシュ済み企業はスキップされ、未収集の企業だけスクレイピングされる。"""
    calls = []
    lawson = _company("lawson")["name"]
    famima = _company("famima")["name"]

    def fake_fetch(self, ids, start, end):
        calls.append(list(ids))
        self.last_status = {cid: ("ok", 200) for cid in ids}
        name_map = {"lawson": lawson, "famima": famima}
        return (
            [_make_item(name_map[cid], url=f"https://example.com/{cid}") for cid in ids],
            ["scraped"],
            [name_map[cid] for cid in ids],
        )

    monkeypatch.setattr(NewsScraper, "fetch_news", fake_fetch)
    service.get_news(["lawson"], "2025-10-25", "2025-10-25")
    assert calls == [["lawson"]]

    items, _, checked, _ = service.get_news(["lawson", "famima"], "2025-10-25", "2025-10-25")
    assert calls == [["lawson"], ["famima"]], "only the un-cached company is scraped"
    assert {i["company_name"] for i in items} == {lawson, famima}
    assert checked == [lawson, famima]
