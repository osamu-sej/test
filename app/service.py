"""収集のオーケストレーション層。

「サーバー側キャッシュ(SQLite)が新しければ DB から返し、
古い企業だけ実際にスクレイピングする」という判断を担う。
画面へ返す形式(items, logs, checked_names)はスクレイパー単体の
出力と互換で、フロントエンドはこの層の存在を意識しない。
"""
import os
import time
from datetime import datetime, timedelta

from .companies import COMPANIES
from .scraper import NewsScraper
from . import storage

# キャッシュの鮮度(秒)。環境変数で調整可能
TTL_TODAY = int(os.environ.get("NEWS_TTL_TODAY", "1800"))    # 今日を含む日付: 30分
TTL_PAST = int(os.environ.get("NEWS_TTL_PAST", "86400"))     # 過去日: 24時間
TTL_ERROR = int(os.environ.get("NEWS_TTL_ERROR", "300"))     # エラーだった企業: 5分で再試行

# coverage 記録の日数上限(異常に広い範囲を指定されたときの暴走防止。
# 上限を超えた分はキャッシュ対象外となり毎回スクレイピングされるだけで、結果は正しい)
MAX_COVERAGE_DAYS = 400


def _date_range(start_str, end_str, cap=MAX_COVERAGE_DAYS):
    try:
        s = datetime.strptime(start_str, "%Y-%m-%d")
        e = datetime.strptime(end_str, "%Y-%m-%d")
    except ValueError:
        return [start_str]
    if e < s:
        return [start_str]
    days = []
    d = s
    while d <= e and len(days) < cap:
        days.append(d.strftime("%Y-%m-%d"))
        d += timedelta(days=1)
    return days


def _is_fresh(cov_entry, day, today_str, now):
    if not cov_entry:
        return False
    fetched_at, status, _code = cov_entry
    if status in ("error", "exception"):
        ttl = TTL_ERROR
    elif day >= today_str:
        ttl = TTL_TODAY
    else:
        ttl = TTL_PAST
    return (now - fetched_at) <= ttl


def get_news(company_ids, start_date_str, end_date_str, force=False):
    """(items, debug_logs, checked_names, last_collected_epoch) を返す。

    - force_link 企業は従来どおり毎回リンク項目を生成
    - キャッシュが新しい企業は DB から返す(403/エラーはフォールバック項目を再構成)
    - それ以外の企業だけ実際にスクレイピングし、結果を DB に保存
    """
    company_map = {c["id"]: c for c in COMPANIES}
    name_to_id = {c["name"]: c["id"] for c in COMPANIES}
    valid_ids = [cid for cid in company_ids if cid in company_map]
    days = _date_range(start_date_str, end_date_str)
    today_str = datetime.now().strftime("%Y-%m-%d")
    now = time.time()

    normal_ids = [cid for cid in valid_ids if company_map[cid].get("scraper_type") != "force_link"]
    force_link_ids = {cid for cid in valid_ids if company_map[cid].get("scraper_type") == "force_link"}

    coverage = {} if force else storage.get_coverage(normal_ids, days)
    stale = set()
    for cid in normal_ids:
        if force or not all(_is_fresh(coverage.get((cid, d)), d, today_str, now) for d in days):
            stale.add(cid)

    # スクレイピング対象(選択順を維持)。force_link は毎回この経路(ネットワークなし)
    scrape_ids = [cid for cid in company_ids if cid in stale or cid in force_link_ids]

    scraper = NewsScraper()
    if scrape_ids:
        items, logs, _checked = scraper.fetch_news(scrape_ids, start_date_str, end_date_str)
    else:
        items, logs = [], [f"=== Range: {start_date_str} ~ {end_date_str} ==="]

    # 実ニュースを保存(company_name → id へ逆引き。未知の企業名は保存しない)
    to_save = []
    for it in items:
        if it and not it.get("is_link_only") and not it.get("is_error"):
            cid = name_to_id.get(it.get("company_name"))
            if cid:
                to_save.append({**it, "company_id": cid})
    if to_save:
        storage.save_items(to_save)

    # 収集結果ステータスを coverage に記録(次回のキャッシュ判断に使う)
    for cid, (status, code) in (getattr(scraper, "last_status", None) or {}).items():
        storage.record_coverage(cid, days, status, code)

    # キャッシュから返す企業ぶんを合成
    cached_ids = [cid for cid in valid_ids if cid not in stale and cid not in force_link_ids]
    for cid in cached_ids:
        company = company_map[cid]
        ent = coverage.get((cid, days[0]))
        status = ent[1] if ent else "ok"
        code = ent[2] if ent else None
        if status == "ok":
            db_items = storage.get_items(cid, start_date_str, end_date_str)
            items.extend(db_items)
            logs.append(f"--- {company['name']}: cache hit ({len(db_items)} items) ---")
        elif status == "404":
            logs.append(f"--- {company['name']}: cache hit (404 skip) ---")
        else:
            fallback = scraper._fallback_item(
                company, start_date_str, code if status in ("403", "error") else None
            )
            if fallback:
                items.append(fallback)
            logs.append(f"--- {company['name']}: cache hit ({status}) ---")

    checked_names = [company_map[cid]["name"] for cid in company_ids if cid in company_map]
    last_collected = storage.latest_fetch_time(normal_ids, days)
    return items, logs, checked_names, last_collected


def collect_all(days_back=1):
    """全企業について「(days_back)日前〜今日」を強制収集する(スケジューラ用)。"""
    today = datetime.now()
    start = (today - timedelta(days=days_back)).strftime("%Y-%m-%d")
    end = today.strftime("%Y-%m-%d")
    ids = [c["id"] for c in COMPANIES]
    items, _logs, _checked, _ = get_news(ids, start, end, force=True)
    return len(items)
