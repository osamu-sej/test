"""SQLite による収集結果の永続化層。

- news_items: スクレイピングで見つかった実ニュース(URL+日付で一意、初出優先)
- coverage:   「どの企業のどの日付を、いつ・どういう結果で収集したか」の記録。
              サービス層はこれを見て再スクレイピングの要否を判断する。

DB パスは環境変数 NEWS_DB_PATH で上書き可能(テストが利用)。
接続のたびに CREATE TABLE IF NOT EXISTS を実行するため、明示的な初期化は不要。
"""
import os
import sqlite3
import time
from pathlib import Path

DEFAULT_DB_PATH = Path(__file__).resolve().parent.parent / "data" / "news.db"


def db_path() -> Path:
    return Path(os.environ.get("NEWS_DB_PATH", str(DEFAULT_DB_PATH)))


def _connect() -> sqlite3.Connection:
    path = db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=30)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("""
        CREATE TABLE IF NOT EXISTS news_items (
            company_id    TEXT NOT NULL,
            company_name  TEXT NOT NULL,
            badge_color   TEXT,
            title         TEXT NOT NULL,
            url           TEXT NOT NULL,
            date          TEXT NOT NULL,
            first_seen_at REAL NOT NULL,
            PRIMARY KEY (url, date)
        )""")
    conn.execute("""
        CREATE TABLE IF NOT EXISTS coverage (
            company_id  TEXT NOT NULL,
            date        TEXT NOT NULL,
            fetched_at  REAL NOT NULL,
            status      TEXT NOT NULL,
            status_code INTEGER,
            PRIMARY KEY (company_id, date)
        )""")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_items_company_date ON news_items(company_id, date)")
    conn.execute("""
        CREATE TABLE IF NOT EXISTS digest_cache (
            cache_key  TEXT PRIMARY KEY,
            created_at REAL NOT NULL,
            content    TEXT NOT NULL
        )""")
    return conn


def init() -> None:
    """テーブル作成だけ行う(起動時に一度呼ぶと以後の接続が速い)。"""
    _connect().close()


def save_items(items) -> int:
    """実ニュース項目を保存する。既存(同一 URL+日付)は初出を優先して無視。
    items の各要素は company_id を含む item dict。保存件数を返す。"""
    if not items:
        return 0
    now = time.time()
    conn = _connect()
    try:
        with conn:
            cur = conn.executemany(
                "INSERT OR IGNORE INTO news_items "
                "(company_id, company_name, badge_color, title, url, date, first_seen_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                [(i["company_id"], i["company_name"], i.get("badge_color"),
                  i["title"], i["url"], i["date"], now) for i in items],
            )
            return cur.rowcount
    finally:
        conn.close()


def get_items(company_id, start_date, end_date):
    """指定企業・日付範囲の保存済みニュースを item dict のリストで返す。"""
    conn = _connect()
    try:
        rows = conn.execute(
            "SELECT company_name, badge_color, title, url, date FROM news_items "
            "WHERE company_id = ? AND date BETWEEN ? AND ? ORDER BY date, rowid",
            (company_id, start_date, end_date),
        ).fetchall()
    finally:
        conn.close()
    return [
        {
            "company_name": r[0],
            "badge_color": r[1],
            "title": r[2],
            "url": r[3],
            "date": r[4],
            "is_link_only": False,
            "is_error": False,
        }
        for r in rows
    ]


def record_coverage(company_id, dates, status, status_code=None) -> None:
    now = time.time()
    conn = _connect()
    try:
        with conn:
            conn.executemany(
                "INSERT INTO coverage (company_id, date, fetched_at, status, status_code) "
                "VALUES (?, ?, ?, ?, ?) "
                "ON CONFLICT(company_id, date) DO UPDATE SET "
                "fetched_at = excluded.fetched_at, status = excluded.status, "
                "status_code = excluded.status_code",
                [(company_id, d, now, status, status_code) for d in dates],
            )
    finally:
        conn.close()


def get_coverage(company_ids, dates):
    """{(company_id, date): (fetched_at, status, status_code)} を返す。"""
    if not company_ids or not dates:
        return {}
    conn = _connect()
    try:
        q_ids = ",".join("?" * len(company_ids))
        q_dates = ",".join("?" * len(dates))
        rows = conn.execute(
            f"SELECT company_id, date, fetched_at, status, status_code FROM coverage "
            f"WHERE company_id IN ({q_ids}) AND date IN ({q_dates})",
            list(company_ids) + list(dates),
        ).fetchall()
    finally:
        conn.close()
    return {(r[0], r[1]): (r[2], r[3], r[4]) for r in rows}


def get_digest(cache_key, max_age_seconds):
    """キャッシュ済みダイジェストを返す(期限切れ・未生成なら None)。"""
    conn = _connect()
    try:
        row = conn.execute(
            "SELECT content, created_at FROM digest_cache WHERE cache_key = ?", (cache_key,)
        ).fetchone()
    finally:
        conn.close()
    if row and (time.time() - row[1]) <= max_age_seconds:
        return row[0]
    return None


def save_digest(cache_key, content) -> None:
    conn = _connect()
    try:
        with conn:
            conn.execute(
                "INSERT INTO digest_cache (cache_key, created_at, content) VALUES (?, ?, ?) "
                "ON CONFLICT(cache_key) DO UPDATE SET created_at = excluded.created_at, "
                "content = excluded.content",
                (cache_key, time.time(), content),
            )
    finally:
        conn.close()


def latest_fetch_time(company_ids, dates):
    """指定範囲の最新収集時刻(epoch 秒)。未収集なら None。"""
    if not company_ids or not dates:
        return None
    conn = _connect()
    try:
        q_ids = ",".join("?" * len(company_ids))
        q_dates = ",".join("?" * len(dates))
        row = conn.execute(
            f"SELECT MAX(fetched_at) FROM coverage "
            f"WHERE company_id IN ({q_ids}) AND date IN ({q_dates})",
            list(company_ids) + list(dates),
        ).fetchone()
    finally:
        conn.close()
    return row[0] if row and row[0] else None
