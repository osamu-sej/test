import hashlib
import json
import re
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path

from fastapi import FastAPI, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

# companies.py から設定を読み込む
from .companies import COMPANIES
# 収集はサービス層(SQLite キャッシュ+スクレイパー)経由で行う
from . import ai, scheduler, service, storage
# NewsScraper はテスト(patch)や既存コードからの参照互換のため re-export
from .scraper import NewsScraper  # noqa: F401

# アプリのバージョン。改修のたびに更新する(画面左下・X-App-Version ヘッダー・/docs に表示される)
APP_VERSION = "1.4.0"

# AI ダイジェストのキャッシュ有効期間(秒)
DIGEST_CACHE_TTL = 1800


@asynccontextmanager
async def lifespan(_app):
    storage.init()
    scheduler_stop = scheduler.start()
    yield
    if scheduler_stop:
        scheduler_stop.set()


app = FastAPI(title="Retail News Scout", version=APP_VERSION, lifespan=lifespan)

BASE_DIR = Path(__file__).resolve().parent
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
templates = Jinja2Templates(directory=BASE_DIR / "templates")

# 日付クエリの形式チェック(不正値は今日にフォールバック。以前は strptime で 500 になっていた)
DATE_PARAM_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def script_safe_json(obj):
    """<script> 内に埋め込んでも安全な JSON 文字列を返す(</script> 挿入対策)。"""
    return json.dumps(obj, ensure_ascii=False).replace("<", "\\u003c")


# ==========================================
#  UI生成ロジック
# ==========================================
def generate_sidebar_html(selected_ids):
    selected_ids = set(selected_ids)
    categories = {}
    for c in COMPANIES:
        categories.setdefault(c["category"], []).append(c)

    html = ""
    for cat, companies in categories.items():
        cat_id = f"cat_{cat}"

        is_category_all_selected = all(comp["id"] in selected_ids for comp in companies)
        parent_checked = "checked" if is_category_all_selected else ""

        html += f"""
        <details class="mb-3 bg-white rounded-xl shadow-sm overflow-hidden">
            <summary class="p-3 bg-slate-50 font-bold cursor-pointer hover:bg-slate-100 flex justify-between items-center select-none transition-colors">
                <div class="flex items-center">
                    <input type="checkbox" {parent_checked} onclick="event.stopPropagation()" onchange="toggleCategory(this, '{cat_id}')" class="mr-3 h-4 w-4 rounded text-blue-600 focus:ring-blue-500 cursor-pointer">
                    <span class="text-slate-700">{cat}</span>
                </div>
                <i class="fas fa-chevron-down text-xs text-slate-400"></i>
            </summary>
            <div class="p-2 space-y-1">
        """
        for comp in companies:
            checked = "checked" if comp["id"] in selected_ids else ""
            html += f"""
                <label class="flex items-center p-2 hover:bg-blue-50 rounded-lg cursor-pointer transition-colors group">
                    <input type="checkbox" name="companies" value="{comp['id']}" {checked} class="{cat_id} mr-3 h-4 w-4 rounded text-blue-600 focus:ring-blue-500">
                    <span class="w-3 h-3 rounded-full mr-3 shadow-sm ring-2 ring-white" style="background-color: {comp['badge_color']}"></span>
                    <span class="text-sm text-slate-600 group-hover:text-slate-900">{comp['name']}</span>
                </label>
            """
        html += "</div></details>"
    return html


@app.get("/", response_class=HTMLResponse)
def read_root(request: Request, start_date: str = Query(None), end_date: str = Query(None), companies: list[str] = Query(None), force: str = Query(None)):
    # 同期関数にすることで FastAPI がスレッドプール上で実行し、
    # スクレイピング中もイベントループが他のリクエストを処理できる

    today_str = datetime.now().strftime("%Y-%m-%d")
    # 初期状態は全選択
    selected_ids = companies if companies else [c["id"] for c in COMPANIES]

    start_date_str = start_date if start_date and DATE_PARAM_RE.match(start_date) else today_str
    end_date_str = end_date if end_date and DATE_PARAM_RE.match(end_date) else today_str

    items, logs, checked_names, last_collected = service.get_news(
        selected_ids, start_date_str, end_date_str, force=(force == "1")
    )
    last_collected_str = (
        datetime.fromtimestamp(last_collected).strftime("%m/%d %H:%M") if last_collected else None
    )

    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={
            "version": APP_VERSION,
            "start_date": start_date_str,
            "end_date": end_date_str,
            "sidebar_html": generate_sidebar_html(selected_ids),
            "items_json": script_safe_json(items),
            "checked_names_json": script_safe_json(checked_names),
            "logs": logs,
            "last_collected": last_collected_str,
            "ai_enabled": ai.is_enabled(),
        },
        headers={
            "Cache-Control": "no-cache, no-store, must-revalidate",
            "Pragma": "no-cache",
            "Expires": "0",
            "X-App-Version": APP_VERSION,
        },
    )


@app.get("/digest")
def get_digest(start_date: str = Query(None), end_date: str = Query(None), companies: list[str] = Query(None)):
    """収集済みニュース(SQLite)から AI ダイジェストを生成して返す。
    スクレイピングは行わない — 先に通常の検索で収集されていることが前提。"""
    if not ai.is_enabled():
        return JSONResponse({"enabled": False, "error": "AI 機能が無効です(ANTHROPIC_API_KEY 未設定)。"})

    today_str = datetime.now().strftime("%Y-%m-%d")
    start_date_str = start_date if start_date and DATE_PARAM_RE.match(start_date) else today_str
    end_date_str = end_date if end_date and DATE_PARAM_RE.match(end_date) else today_str
    valid_ids = {c["id"] for c in COMPANIES}
    selected_ids = [cid for cid in (companies or []) if cid in valid_ids] or [c["id"] for c in COMPANIES]

    items = []
    for cid in selected_ids:
        items.extend(storage.get_items(cid, start_date_str, end_date_str))
    items.sort(key=lambda i: i["date"])

    if not items:
        return JSONResponse({
            "enabled": True,
            "digest": None,
            "message": "この期間の収集済みニュースがありません。先に「SEARCH NEWS」で収集してください。",
        })

    # 同一条件+同一ニュース集合なら30分間はキャッシュを返す(API コスト削減)
    key_src = f"{start_date_str}|{end_date_str}|{','.join(sorted(selected_ids))}|" + \
              "|".join(sorted(i["url"] for i in items))
    cache_key = hashlib.sha256(key_src.encode()).hexdigest()
    cached = storage.get_digest(cache_key, DIGEST_CACHE_TTL)
    if cached:
        return JSONResponse({"enabled": True, "digest": cached, "cached": True, "item_count": len(items)})

    try:
        digest = ai.generate_digest(items, start_date_str, end_date_str)
    except ai.AIDigestError as exc:
        return JSONResponse({"enabled": True, "error": str(exc)}, status_code=502)

    storage.save_digest(cache_key, digest)
    return JSONResponse({"enabled": True, "digest": digest, "cached": False, "item_count": len(items)})
