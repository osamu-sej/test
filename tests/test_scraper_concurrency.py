"""スクレイピングの同時並列数(FETCH_MAX_WORKERS)の設定テスト。

小さいホスティング環境でのメモリ超過対策として、環境変数
NEWS_FETCH_MAX_WORKERS で並列数を調整できることを確認する。
"""
import importlib

from app import scraper


def test_default_fetch_max_workers_is_conservative(monkeypatch):
    monkeypatch.delenv("NEWS_FETCH_MAX_WORKERS", raising=False)
    reloaded = importlib.reload(scraper)
    assert reloaded.FETCH_MAX_WORKERS == 5
    importlib.reload(scraper)  # 元の環境変数状態に戻す


def test_fetch_max_workers_overridable_by_env(monkeypatch):
    monkeypatch.setenv("NEWS_FETCH_MAX_WORKERS", "2")
    reloaded = importlib.reload(scraper)
    try:
        assert reloaded.FETCH_MAX_WORKERS == 2
    finally:
        monkeypatch.delenv("NEWS_FETCH_MAX_WORKERS", raising=False)
        importlib.reload(scraper)
