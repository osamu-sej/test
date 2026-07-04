"""定時自動収集。バックグラウンドスレッドで全企業のニュースを定期収集し、
ユーザーがページを開いたときは SQLite キャッシュから即応答できるようにする。

環境変数:
- NEWS_SCHEDULER=off              スケジューラを無効化(テスト等)
- NEWS_SCHEDULER_INTERVAL=1800    収集間隔(秒)
- NEWS_SCHEDULER_INITIAL_DELAY=15 起動から初回収集までの待ち(秒)
"""
import logging
import os
import threading

logger = logging.getLogger("uvicorn.error")


def start():
    """スケジューラスレッドを開始し、停止用の Event を返す(無効時は None)。"""
    if os.environ.get("NEWS_SCHEDULER", "on").lower() in ("off", "0", "false"):
        return None
    interval = int(os.environ.get("NEWS_SCHEDULER_INTERVAL", "1800"))
    initial_delay = int(os.environ.get("NEWS_SCHEDULER_INITIAL_DELAY", "15"))
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
