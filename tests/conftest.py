import os
import sys

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

# テスト中はバックグラウンドの定時収集を無効化
os.environ.setdefault("NEWS_SCHEDULER", "off")

import pytest


@pytest.fixture(autouse=True)
def _isolated_db(tmp_path, monkeypatch):
    """各テストを独立した一時 SQLite DB で実行する。"""
    monkeypatch.setenv("NEWS_DB_PATH", str(tmp_path / "news.db"))
