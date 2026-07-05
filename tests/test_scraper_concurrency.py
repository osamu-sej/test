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


def test_fetch_max_workers_falls_back_on_invalid_value(monkeypatch):
    """空文字や数値でない値では import 自体を失敗させず、既定値にフォールバックする。"""
    for bad_value in ("", "abc", "  "):
        monkeypatch.setenv("NEWS_FETCH_MAX_WORKERS", bad_value)
        try:
            reloaded = importlib.reload(scraper)
            assert reloaded.FETCH_MAX_WORKERS == 5, f"failed for {bad_value!r}"
        finally:
            monkeypatch.delenv("NEWS_FETCH_MAX_WORKERS", raising=False)
            importlib.reload(scraper)


def test_fetch_max_workers_clamped_to_at_least_one(monkeypatch):
    """0 以下の値は ThreadPoolExecutor が拒否するため、最低 1 に切り上げる。"""
    for bad_value in ("0", "-3"):
        monkeypatch.setenv("NEWS_FETCH_MAX_WORKERS", bad_value)
        try:
            reloaded = importlib.reload(scraper)
            assert reloaded.FETCH_MAX_WORKERS == 1, f"failed for {bad_value!r}"
        finally:
            monkeypatch.delenv("NEWS_FETCH_MAX_WORKERS", raising=False)
            importlib.reload(scraper)
