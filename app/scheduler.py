"""定時自動収集。バックグラウンドスレッドで全企業のニュースを定期収集し、
ユーザーがページを開いたときは SQLite キャッシュから即応答できるようにする。

環境変数:
- NEWS_SCHEDULER=off              スケジューラを無効化(テスト等)
- NEWS_SCHEDULER_INTERVAL=43200   収集間隔(秒)。既定は12時間おき
- NEWS_SCHEDULER_INITIAL_DELAY=15 起動から初回収集までの待ち(秒)
"""
import logging
import os
import threading

from .envutil import env_int

logger = logging.getLogger("uvicorn.error")

# 既定の収集間隔: 12時間。頻繁な全社収集はメモリ・CPU のピークを生むため、
# 小さいホスティング環境でも安全な頻度を既定とする(ページを開いたときの
# オンデマンド収集は別途キャッシュ鮮度 TTL に従って行われる)
DEFAULT_INTERVAL_SECONDS = 43200


def start():
    """スケジューラスレッドを開始し、停止用の Event を返す(無効時は None)。"""
    if os.environ.get("NEWS_SCHEDULER", "on").lower() in ("off", "0", "false"):
        return None
    interval = env_int("NEWS_SCHEDULER_INTERVAL", DEFAULT_INTERVAL_SECONDS, minimum=60)
    initial_delay = env_int("NEWS_SCHEDULER_INITIAL_DELAY", 15, minimum=0)
    stop_event = threading.Event()

    def loop():
        from . import service
        stop_event.wait(initial_delay)
        while not stop_event.is_set():
            try:
                count = service.collect_all(days_back=1)
                logger.info("[scheduler] collected %d items", count)
            except Exception:
                logger.exception("[scheduler] collection failed")
            stop_event.wait(interval)

    threading.Thread(target=loop, daemon=True, name="news-scheduler").start()
    logger.info("[scheduler] started (interval=%ss)", interval)
    return stop_event
