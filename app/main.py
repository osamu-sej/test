import json
import re
import unicodedata
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from urllib.parse import urljoin, urlparse, urlunparse
import requests
from bs4 import BeautifulSoup
from fastapi import FastAPI, Query, Response
from fastapi.responses import HTMLResponse

# companies.py から設定を読み込む
from .companies import COMPANIES

app = FastAPI(title="Retail News Scout")

# 日付抽出用の正規表現(要素ごとに再コンパイルしないよう事前コンパイル)
DATE_FLEX_FINDALL_RE = re.compile(r"\d{4}\s*[./年]\s*\d{1,2}\s*[./月]\s*\d{1,2}")
DATE_FLEX_CAPTURE_RE = re.compile(r"(\d{4})\s*[./年]\s*(\d{1,2})\s*[./月]\s*(\d{1,2})")
DATE_STRIP_RE = re.compile(r"20\d{2}\s*[./年]\s*\d{1,2}\s*[./月]\s*\d{1,2}\s*日?")
LIFE_DATE_RE = re.compile(r"20\d{2}/\d{1,2}/\d{1,2}")
WHITESPACE_RE = re.compile(r"\s+")

REQUEST_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7",
    "Accept-Language": "ja,en-US;q=0.9,en;q=0.8",
    "Referer": "https://www.google.com/",
    "Connection": "keep-alive"
}

# 同時に張る接続数の上限(相手サイトはすべて別ドメインなので各サイトへは1接続)
FETCH_MAX_WORKERS = 10

# ==========================================
#  スクレイピングロジック (NewsScraper)
# ==========================================
class NewsScraper:
    def __init__(self) -> None:
        self.session = requests.Session()
        self.session.headers.update(REQUEST_HEADERS)

    def _fetch_one(self, url):
        """1サイト分の GET。並列実行のためスレッドごとに独立した Session を使う。
        例外は握りつぶさず呼び出し側で従来どおり処理できるよう値として返す。"""
        session = requests.Session()
        session.headers.update(REQUEST_HEADERS)
        try:
            return session.get(url, timeout=10.0)
        except Exception as exc:
            return exc
        finally:
            session.close()

    def _fallback_item(self, company, target_date_str, status_code=None):
        if status_code == 403:
            title = "🔒 公式サイトで最新ニュースを確認する"
            badge_color = "#3b82f6" 
            is_link_only = True
        elif status_code == 404:
            return None 
        else:
            code_str = f" ({status_code})" if status_code else ""
            title = f"【エラー】公式サイトを開く{code_str}"
            badge_color = company["badge_color"]
            is_link_only = True
        
        return {
            "company_name": company["name"],
            "badge_color": badge_color,
            "title": title,
            "url": company["url"],
            "date": target_date_str,
            "is_link_only": is_link_only, 
            "is_error": True if status_code != 403 else False
        }

    def fetch_news(self, company_ids, start_date_str, end_date_str):
        start_date = datetime.strptime(start_date_str, "%Y-%m-%d")
        end_date = datetime.strptime(end_date_str, "%Y-%m-%d")
        all_items = []
        debug_logs = []
        checked_company_names = []
        debug_logs.append(f"=== Range: {start_date_str} ~ {end_date_str} ===")

        # id からの企業ルックアップ用(ループ内で毎回線形探索しないため)
        company_map = {c["id"]: c for c in COMPANIES}

        # HTTP取得だけを先に並列実行する(ページの解析・結果の並び・ログは
        # 従来どおり company_ids の順に直列処理するので出力は変わらない)
        fetch_targets = [
            cid for cid in company_ids
            if cid in company_map and company_map[cid].get("scraper_type") != "force_link"
        ]
        prefetched = {}
        if fetch_targets:
            with ThreadPoolExecutor(max_workers=min(FETCH_MAX_WORKERS, len(fetch_targets))) as pool:
                for cid, result in zip(
                    fetch_targets,
                    pool.map(lambda c: self._fetch_one(company_map[c]["url"]), fetch_targets),
                ):
                    prefetched[cid] = result

        for cid in company_ids:
            company = company_map.get(cid)
            if not company: continue
            
            # ★修正：ここも抜けていました！リストに追加します
            checked_company_names.append(company["name"])
            debug_logs.append(f"--- Checking {company['name']} ---")

            if company.get("scraper_type") == "force_link":
                all_items.append({
                    "company_name": company["name"],
                    "badge_color": "#3b82f6",
                    "title": "👉 公式サイトで最新ニュースを見る",
                    "url": company["url"],
                    "date": start_date_str,
                    "is_link_only": True,
                    "is_error": False
                })
                continue

            html_content = None

            try:
                resp = prefetched[cid]
                if isinstance(resp, Exception):
                    raise resp
                resp.encoding = resp.apparent_encoding
                
                if resp.status_code == 404:
                    debug_logs.append(f"Status 404: Page not found. Skipped.")
                    continue
                elif resp.status_code == 403:
                    debug_logs.append("Status 403 (Access Denied). Fallback to link.")
                    all_items.append(self._fallback_item(company, start_date_str, 403))
                    continue
                elif resp.status_code != 200:
                    debug_logs.append(f"Error Status: {resp.status_code}")
                    all_items.append(self._fallback_item(company, start_date_str, resp.status_code))
                    continue
                else:
                    html_content = resp.text

                soup = BeautifulSoup(html_content, "html.parser")
                
            except Exception as exc:
                debug_logs.append(f"Exception: {exc}")
                all_items.append(self._fallback_item(company, start_date_str))
                continue

            found_count = 0
            
            # --- ライフ専用ロジック (構造が特殊なため維持) ---
            if company["id"] == "life":
                life_dates = soup.find_all(string=LIFE_DATE_RE)
                candidates_map = {} 
                for date_node in life_dates:
                    try:
                        date_text = date_node.strip()
                        y, m, d = date_text.split("/")
                        found_date_str = f"{y}-{int(m):02d}-{int(d):02d}"
                        if start_date_str <= found_date_str <= end_date_str:
                            card_node = date_node.parent
                            link_node = None
                            for _ in range(5):
                                if not card_node: break
                                if card_node.name == 'a' and card_node.has_attr('href'):
                                    link_node = card_node
                                    break
                                found_child_link = card_node.find('a', href=True)
                                if found_child_link:
                                    link_node = found_child_link
                                    break
                                card_node = card_node.parent
                            
                            if not link_node or not card_node: continue

                            raw_url = urljoin(company["url"], link_node['href'])
                            parsed = urlparse(raw_url)
                            clean_url = urlunparse((parsed.scheme, parsed.netloc, parsed.path, '', '', ''))

                            title_candidates = []
                            img = card_node.find('img', alt=True)
                            if img and len(img['alt'].strip()) > 1:
                                title_candidates.append(img['alt'].strip())
                            
                            link_text = link_node.get_text(" ", strip=True)
                            if len(link_text) > 1:
                                title_candidates.append(link_text)
                                
                            card_full_text = card_node.get_text(" ", strip=True)
                            ignore_words = [date_text, "社会・環境", "商品・サービス", "新店・改装", "その他", "すべて", "NEW", "お知らせ", "ニュースリリース", "重要なお知らせ"]
                            for w in ignore_words:
                                card_full_text = card_full_text.replace(w, "")
                            clean_card_text = WHITESPACE_RE.sub(' ', card_full_text).strip()
                            if len(clean_card_text) > 1:
                                title_candidates.append(clean_card_text)

                            best_title = ""
                            if title_candidates:
                                best_title = max(title_candidates, key=len)
                            
                            if not best_title: best_title = "【ライフ】ニュース詳細"

                            if clean_url not in candidates_map:
                                candidates_map[clean_url] = {
                                    "company_name": company["name"],
                                    "badge_color": company["badge_color"],
                                    "title": best_title,
                                    "url": clean_url,
                                    "date": found_date_str,
                                    "is_link_only": False,
                                    "is_error": False
                                }
                            else:
                                if len(best_title) > len(candidates_map[clean_url]["title"]):
                                    candidates_map[clean_url]["title"] = best_title

                    except Exception as e:
                        debug_logs.append(f"Life error: {e}")
                        continue
                
                for item in candidates_map.values():
                    all_items.append(item)
                    found_count += 1
                    debug_logs.append(f"  -> Found (Life Best): {item['title'][:15]}...")

            # --- 汎用ロジック (コンビニも含む全企業用) ---
            # 「採点」や「強力検索」などの余計なことはせず、シンプルに探す
            if found_count == 0:
                target_tags = soup.find_all(['dt', 'dd', 'li', 'div', 'p', 'span', 'time', 'td', 'tr'])
                processed_urls = set()

                for element in target_tags:
                    full_text = unicodedata.normalize("NFKC", element.get_text(" ", strip=True))
                    if len(full_text) > 500: continue

                    # 複数の日付を含む要素はコンテナ（複数ニュースの親要素）なのでスキップ
                    all_date_matches = DATE_FLEX_FINDALL_RE.findall(full_text)
                    if len(all_date_matches) > 1: continue

                    match = DATE_FLEX_CAPTURE_RE.search(full_text)
                    if not match: continue
                    y, m, d = match.groups()
                    found_date_str = f"{y}-{int(m):02d}-{int(d):02d}"

                    if start_date_str <= found_date_str <= end_date_str:
                        if company["id"] == "life": continue # ライフは済んでいるのでスキップ

                        debug_logs.append(f"★ MATCH: {found_date_str} in <{element.name}>")
                        link_tag = None

                        # 1. dtなら隣のddを見る (よくあるパターン)
                        if element.name == 'dt':
                            dd_node = element.find_next_sibling('dd')
                            if dd_node: link_tag = dd_node.find('a', href=True)

                        # 2. 自分自身の中にリンクがあるか
                        if not link_tag: link_tag = element.find('a', href=True)

                        # 3. 親や兄弟を探す (少し範囲を広げる)
                        if not link_tag:
                            curr = element
                            for _ in range(5):
                                if not curr: break
                                if curr.name == 'a' and curr.has_attr('href'):
                                    link_tag = curr
                                    break
                                # 親要素が複数日付を含む場合はコンテナなので探索を中止
                                if curr != element:
                                    parent_text = unicodedata.normalize("NFKC", curr.get_text(" ", strip=True))
                                    parent_dates = DATE_FLEX_FINDALL_RE.findall(parent_text)
                                    if len(parent_dates) > 1:
                                        break
                                # 親の要素内にある他のリンクを探す（行全体がリンクになっていない場合など）
                                if curr.name in ['li', 'tr', 'article', 'td'] or (curr.name=='div' and any(c in str(curr.get('class')) for c in ['item', 'news', 'col', 'block'])):
                                    links = curr.find_all("a", href=True)
                                    valid = [l for l in links if len(l.get_text(strip=True)) > 4] # 短すぎるリンクは無視
                                    if valid:
                                        # 一番文字数が長いリンクを採用（「詳細」などよりタイトルを選ぶため）
                                        link_tag = max(valid, key=lambda l: len(l.get_text(strip=True)))
                                        break
                                curr = curr.parent

                        if link_tag and link_tag.get("href"):
                            title = link_tag.get_text(strip=True)
                            url = urljoin(company["url"], link_tag["href"])

                            # タイトル補完 (リンク自体に文字がない場合、親要素のテキストを使う)
                            if not title or len(title) < 5:
                                if link_tag.parent:
                                    parent_text = link_tag.parent.get_text(" ", strip=True)
                                    # 日付だけ削除してタイトルにする
                                    clean_title = DATE_STRIP_RE.sub("", parent_text).strip()
                                    if len(clean_title) > 5:
                                        title = clean_title
                                    else:
                                        title = "ニュース詳細"

                            if url not in processed_urls:
                                all_items.append({
                                    "company_name": company["name"],
                                    "badge_color": company["badge_color"],
                                    "title": title[:100] + "..." if len(title) > 100 else title,
                                    "url": url,
                                    "date": found_date_str,
                                    "is_link_only": False,
                                    "is_error": False
                                })
                                processed_urls.add(url)
                                found_count += 1
                                debug_logs.append(f"  -> Found: {title[:15]}...")
                                # あえて break しない（同じ日に複数ニュースがある場合のため）
            
            if found_count == 0:
                debug_logs.append("Result: 0 items found.")

        return all_items, debug_logs, checked_company_names

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
def read_root(start_date: str = Query(None), end_date: str = Query(None), companies: list[str] = Query(None), response: Response = None):
    # 同期関数にすることで FastAPI がスレッドプール上で実行し、
    # スクレイピング中もイベントループが他のリクエストを処理できる

    today = datetime.now()
    # 初期状態は全選択
    selected_ids = companies if companies else [c["id"] for c in COMPANIES]

    today_str = today.strftime("%Y-%m-%d")
    start_date_str = start_date if start_date else today_str
    end_date_str = end_date if end_date else today_str

    items, logs, checked_names = NewsScraper().fetch_news(selected_ids, start_date_str, end_date_str)
    
    sidebar_html = generate_sidebar_html(selected_ids)
    items_json = json.dumps(items, ensure_ascii=False)
    checked_names_json = json.dumps(checked_names, ensure_ascii=False)
    logs_html = "<br>".join(logs)
    
    debug_section = f"""
    <div class="mt-16 pt-6 border-t border-slate-200">
        <details class="bg-slate-800 text-green-300 p-5 rounded-xl text-xs font-mono shadow-inner">
            <summary class="cursor-pointer font-bold mb-3 flex items-center hover:text-white transition-colors">
                <i class="fas fa-bug mr-2"></i>Debug Log (調査用)
            </summary>
            <div class="whitespace-pre-wrap leading-relaxed opacity-90 h-64 overflow-y-auto custom-scrollbar">{logs_html}</div>
        </details>
    </div>
    """

    if response:
        response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"

    return f"""
    <!DOCTYPE html>
    <html lang="ja" class="h-full bg-slate-50">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Retail News Scout</title>
        <script src="https://cdn.tailwindcss.com"></script>
        <link href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css" rel="stylesheet">
        <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;700;900&display=swap" rel="stylesheet">
        <style>
            body {{ font-family: 'Inter', sans-serif; }}
            .custom-scrollbar::-webkit-scrollbar {{ width: 8px; }}
            .custom-scrollbar::-webkit-scrollbar-track {{ background: rgba(255,255,255,0.05); }}
            .custom-scrollbar::-webkit-scrollbar-thumb {{ background: rgba(255,255,255,0.2); border-radius: 4px; }}
            details > summary {{ list-style: none; }}
            details > summary::-webkit-details-marker {{ display: none; }}
            .loader {{
                border: 4px solid #f3f3f3;
                border-top: 4px solid #3b82f6;
                border-radius: 50%;
                width: 40px;
                height: 40px;
                animation: spin 1s linear infinite;
            }}
            @keyframes spin {{ 0% {{ transform: rotate(0deg); }} 100% {{ transform: rotate(360deg); }} }}
            
            .filter-btn.active {{
                background-color: #3b82f6;
                color: white;
                border-color: #3b82f6;
            }}
            mark {{
                background-color: #fef08a;
                color: inherit;
                padding: 0 2px;
                border-radius: 2px;
            }}
            #summary-modal > div {{
                max-height: 90vh;
                display: flex;
                flex-direction: column;
            }}
            #summary-scroll-area {{
                max-height: calc(90vh - 12rem);
                overflow-y: auto !important;
            }}
            #detail-news-list {{
                max-height: calc(90vh - 10rem);
                overflow-y: auto !important;
            }}
        </style>
        <script>
            function toggleCategory(source, cls) {{
                document.querySelectorAll('.' + cls).forEach(el => el.checked = source.checked);
            }}
            
            const STORAGE_KEY = 'retail_news_date_cache_v1';

            function getCache() {{
                const data = localStorage.getItem(STORAGE_KEY);
                return data ? JSON.parse(data) : {{}};
            }}

            function formatDate(d) {{
                const y = d.getFullYear();
                const m = String(d.getMonth() + 1).padStart(2, '0');
                const day = String(d.getDate()).padStart(2, '0');
                return `${{y}}-${{m}}-${{day}}`;
            }}

            function parseDate(str) {{
                const parts = str.split('-');
                return new Date(parseInt(parts[0]), parseInt(parts[1]) - 1, parseInt(parts[2]));
            }}

            function shiftRange(amount) {{
                const startInput = document.getElementById('startDateInput');
                const endInput = document.getElementById('endDateInput');
                if (!startInput.value || !endInput.value) return;
                const s = parseDate(startInput.value);
                const e = parseDate(endInput.value);
                const rangeDays = Math.round((e - s) / (1000 * 60 * 60 * 24)) + 1;
                const shift = amount * rangeDays;
                s.setDate(s.getDate() + shift);
                e.setDate(e.getDate() + shift);
                startInput.value = formatDate(s);
                endInput.value = formatDate(e);
                renderFromCacheRange();
            }}

            function setQuickRange(mode) {{
                const today = new Date();
                const todayStr = formatDate(today);
                const startInput = document.getElementById('startDateInput');
                const endInput = document.getElementById('endDateInput');
                if (mode === 'today') {{
                    startInput.value = todayStr;
                    endInput.value = todayStr;
                }} else if (mode === 'week') {{
                    const weekAgo = new Date(today);
                    weekAgo.setDate(weekAgo.getDate() - 6);
                    startInput.value = formatDate(weekAgo);
                    endInput.value = todayStr;
                }} else if (mode === 'month') {{
                    const monthAgo = new Date(today);
                    monthAgo.setDate(monthAgo.getDate() - 29);
                    startInput.value = formatDate(monthAgo);
                    endInput.value = todayStr;
                }}
                renderFromCacheRange();
            }}

            document.addEventListener('DOMContentLoaded', function() {{
                const form = document.querySelector('form');
                const loader = document.getElementById('loading-overlay');
                const startInput = document.getElementById('startDateInput');
                const endInput = document.getElementById('endDateInput');
                const searchInput = document.getElementById('keywordInput');

                if(form && loader) {{
                    form.addEventListener('submit', function() {{
                        loader.classList.remove('hidden');
                        loader.classList.add('flex');
                    }});
                }}

                const SERVER_RESULTS = {items_json};
                const CHECKED_NAMES = {checked_names_json};
                const START_DATE = "{start_date_str}";
                const END_DATE = "{end_date_str}";

                updateCacheAndRender(START_DATE, END_DATE, SERVER_RESULTS, CHECKED_NAMES);

                startInput.addEventListener('change', function() {{ renderFromCacheRange(); }});
                endInput.addEventListener('change', function() {{ renderFromCacheRange(); }});

                searchInput.addEventListener('input', function(e) {{
                    const keyword = e.target.value;
                    filterNews('search', keyword);
                }});
            }});

            function updateCacheAndRender(startDate, endDate, newItems, checkedNames) {{
                let cache = getCache();

                // Group new items by their date
                const byDate = {{}};
                if (newItems && newItems.length > 0) {{
                    newItems.forEach(item => {{
                        const dk = item.date || startDate;
                        if (!byDate[dk]) byDate[dk] = [];
                        byDate[dk].push(item);
                    }});
                }}

                // Update cache for each date that has new items
                const checkedSet = (checkedNames && checkedNames.length > 0) ? new Set(checkedNames) : null;

                // For dates in range, clear checked companies and merge new items
                const s = parseDate(startDate);
                const e = parseDate(endDate);
                for (let d = new Date(s); d <= e; d.setDate(d.getDate() + 1)) {{
                    const dk = formatDate(d);
                    let dateItems = cache[dk] || [];

                    if (checkedSet) {{
                        dateItems = dateItems.filter(item => !checkedSet.has(item.company_name));
                    }}

                    const newDateItems = byDate[dk] || [];
                    newDateItems.forEach(item => {{
                        if (!dateItems.some(saved => saved.url === item.url)) {{
                            dateItems.push(item);
                        }}
                    }});

                    cache[dk] = dateItems;
                }}

                localStorage.setItem(STORAGE_KEY, JSON.stringify(cache));
                renderFromCacheRange();
            }}

            function getDateRange() {{
                const startDate = document.getElementById('startDateInput').value;
                const endDate = document.getElementById('endDateInput').value;
                return {{ startDate, endDate }};
            }}

            function collectItemsInRange(startDate, endDate) {{
                const cache = getCache();
                let allItems = [];
                const s = parseDate(startDate);
                const e = parseDate(endDate);
                for (let d = new Date(s); d <= e; d.setDate(d.getDate() + 1)) {{
                    const dk = formatDate(d);
                    const dateItems = cache[dk] || [];
                    allItems = allItems.concat(dateItems);
                }}
                // Deduplicate by URL
                const seen = new Set();
                allItems = allItems.filter(item => {{
                    if (seen.has(item.url)) return false;
                    seen.add(item.url);
                    return true;
                }});
                allItems.sort((a, b) => new Date(b.date) - new Date(a.date));
                return allItems;
            }}

            function renderFromCacheRange() {{
                const {{ startDate, endDate }} = getDateRange();
                const kw = document.getElementById('keywordInput').value;
                if (kw) {{
                    filterNews('search', kw);
                }} else {{
                    const items = collectItemsInRange(startDate, endDate);
                    renderGrid(items, startDate, endDate);
                }}
            }}
            
            function deleteItem(dateKey, url) {{
                let cache = getCache();
                if (cache[dateKey]) {{
                    cache[dateKey] = cache[dateKey].filter(item => item.url !== url);
                    localStorage.setItem(STORAGE_KEY, JSON.stringify(cache));
                    renderFromCacheRange();
                }}
            }}

            const TOPIC_KEYWORDS = {{
                'product': ['商品', '発売', 'キャンペーン', 'コラボ', '限定', 'フェア', 'プレゼント', 'セール', 'アイス', '弁当', 'スイーツ', 'グッズ', '予約', 'メニュー'],
                'csr': ['環境', 'サステナ', 'エコ', 'CO2', '寄贈', '募金', '支援', 'フードバンク', 'リサイクル', '脱炭素', '賞'],
                'corporate': ['人事', '組織', '決算', '社長', '役員', '提携', '買収', '方針', '報告', 'IR', '株式'],
                'store': ['店舗', '店', 'オープン', '改装', '地域', '地産', '県', '市', '都', '府', '建築', '開発'],
                'dx': ['アプリ', 'DX', 'システム', 'デジタル', '決済', 'AI', 'ロボット']
            }};

            let currentFilterMode = 'category'; 
            let currentCategory = 'all';
            let currentSearchText = '';
            let dashboardMonth = '';

            function filterNews(mode, value) {{
                currentFilterMode = mode;
                const {{ startDate, endDate }} = getDateRange();
                let itemsToDisplay = [];
                const cache = getCache();

                if (mode === 'search') {{
                    currentSearchText = value;
                    if (currentSearchText) {{
                        // Search across all cached data
                        Object.keys(cache).forEach(key => {{
                            itemsToDisplay = itemsToDisplay.concat(cache[key]);
                        }});
                        const seen = new Set();
                        itemsToDisplay = itemsToDisplay.filter(item => {{
                            if (seen.has(item.url)) return false;
                            seen.add(item.url);
                            return true;
                        }});
                        itemsToDisplay.sort((a, b) => new Date(b.date) - new Date(a.date));
                        document.querySelectorAll('.filter-btn').forEach(btn => btn.classList.remove('active'));
                    }} else {{
                        itemsToDisplay = collectItemsInRange(startDate, endDate);
                    }}
                }} else if (mode === 'category') {{
                    currentCategory = value;
                    currentSearchText = '';
                    document.getElementById('keywordInput').value = '';
                    document.querySelectorAll('.filter-btn').forEach(btn => btn.classList.remove('active'));
                    document.getElementById('btn-' + value).classList.add('active');
                    itemsToDisplay = collectItemsInRange(startDate, endDate);
                }}
                renderGrid(itemsToDisplay, startDate, endDate);
            }}

            function checkFilter(title) {{
                if (currentFilterMode === 'search') {{
                    if (!currentSearchText) return true;
                    return title.toLowerCase().includes(currentSearchText.toLowerCase());
                }} else {{
                    if (currentCategory === 'all') return true;
                    const keywords = TOPIC_KEYWORDS[currentCategory] || [];
                    return keywords.some(kw => title.includes(kw));
                }}
            }}
            
            function highlightText(text, keyword) {{
                if (!keyword) return text;
                const regex = new RegExp(`(${{keyword}})`, 'gi');
                return text.replace(regex, '<mark>$1</mark>');
            }}

            function renderGrid(items, startDate, endDate) {{
                const gridContainer = document.getElementById('result-grid');
                const linkContainer = document.getElementById('link-only-container');
                const countBadge = document.getElementById('result-count');
                const emptyMsg = document.getElementById('empty-message');
                const dateDisplay = document.getElementById('display-date-str');

                if (dateDisplay) {{
                    if (currentFilterMode === 'search' && currentSearchText) {{
                        dateDisplay.textContent = 'Search: all cached data';
                    }} else if (startDate === endDate) {{
                        dateDisplay.textContent = 'Target: ' + startDate;
                    }} else {{
                        dateDisplay.textContent = 'Range: ' + startDate + ' ~ ' + (endDate || startDate);
                    }}
                }}

                const filteredItems = items.filter(item => checkFilter(item.title));

                if (!filteredItems || filteredItems.length === 0) {{
                    gridContainer.innerHTML = '';
                    linkContainer.innerHTML = '';
                    if (emptyMsg) {{
                        emptyMsg.classList.remove('hidden');
                        const isFiltering = (currentFilterMode === 'search' && currentSearchText) || (currentFilterMode === 'category' && currentCategory !== 'all');
                        const msgText = (items.length > 0 && isFiltering) ? "条件に一致するニュースはありません" : "まだデータがありません";
                        emptyMsg.querySelector('p.text-xl').textContent = msgText;
                    }}
                    if (countBadge) countBadge.textContent = '0 items';
                    return;
                }}
                
                if (emptyMsg) emptyMsg.classList.add('hidden');
                if (countBadge) countBadge.textContent = filteredItems.length + ' items';
                
                const linkOnlyItems = filteredItems.filter(i => i.is_link_only);
                const cardItems = filteredItems.filter(i => !i.is_link_only);

                gridContainer.innerHTML = cardItems.map(item => {{
                    let bgClass = "bg-white";
                    let textClass = "text-slate-800";
                    if (item.is_error) {{
                        bgClass = "bg-red-50/80";
                        textClass = "text-red-700 font-bold";
                    }}
                    if (item.title && item.title.includes("【") && !item.is_error) {{
                        bgClass = "bg-red-50/80";
                        textClass = "text-red-700 font-bold";
                    }}

                    let displayTitle = item.title;
                    if (currentFilterMode === 'search' && currentSearchText) {{
                        displayTitle = highlightText(item.title, currentSearchText);
                    }}
                    return `
                    <div class="relative ${{bgClass}} p-6 rounded-xl shadow-md border-t-4 hover:-translate-y-1 hover:shadow-lg transition-all duration-200 ease-out group flex flex-col h-full news-card" style="border-color: ${{item.badge_color}}">
                        <div class="flex items-center justify-between mb-4">
                            <div class="flex items-center">
                                <img src="https://www.google.com/s2/favicons?domain=${{item.url}}&sz=32" alt="ロゴ" class="w-5 h-5 mr-3 rounded-full shadow-sm bg-white p-0.5 opacity-80">
                                <span class="text-xs font-bold text-slate-500 uppercase tracking-wider">${{item.company_name}}</span>
                            </div>
                            <span class="text-xs font-medium text-slate-400 bg-slate-100 px-2 py-1 rounded-full whitespace-nowrap"><i class="far fa-calendar-alt mr-1"></i>${{item.date}}</span>
                        </div>
                        <a href="${{item.url}}" target="_blank" class="block flex-1 flex flex-col group-hover:opacity-100">
                            <h3 class="text-lg font-bold ${{textClass}} leading-snug group-hover:text-blue-600 transition-colors flex-grow">
                                ${{displayTitle}}
                            </h3>
                            <div class="mt-5 flex items-center text-sm text-blue-600 font-bold opacity-0 -translate-x-2 group-hover:opacity-100 group-hover:translate-x-0 transition-all duration-300">
                                <span>Read Article</span><i class="fas fa-arrow-right ml-2"></i>
                            </div>
                        </a>
                        <button onclick="deleteItem('${{item.date}}', '${{item.url}}')" class="absolute top-2 right-2 text-slate-200 hover:text-red-400 opacity-0 group-hover:opacity-100 transition-opacity p-1" title="削除"><i class="fas fa-times-circle"></i></button>
                    </div>`;
                }}).join('');

                if (linkOnlyItems.length > 0) {{
                    linkContainer.classList.remove('hidden');
                    linkContainer.innerHTML = `
                        <h3 class="col-span-full text-sm font-bold text-slate-500 mb-2 mt-8">
                            ※直接確認できなかったサイト（公式サイトへ移動）
                        </h3>
                    ` + linkOnlyItems.map(item => `
                        <a href="${{item.url}}" target="_blank" class="flex items-center justify-between p-3 bg-blue-50 border border-blue-200 rounded-lg hover:bg-blue-100 transition-colors group shadow-sm">
                            <div class="flex items-center overflow-hidden">
                                <span class="w-2.5 h-2.5 rounded-full bg-blue-500 mr-3 flex-shrink-0"></span>
                                <span class="font-bold text-blue-700 text-sm mr-3 whitespace-nowrap">${{item.company_name}}</span>
                                <span class="text-sm text-slate-600 truncate group-hover:text-blue-800">${{item.title}}</span>
                            </div>
                            <div class="flex items-center flex-shrink-0 ml-2">
                                <span class="text-xs text-slate-400 mr-2">${{item.date}}</span>
                                <i class="fas fa-external-link-alt text-blue-400 group-hover:text-blue-600"></i>
                            </div>
                        </a>
                    `).join('');
                }} else {{
                    linkContainer.classList.add('hidden');
                    linkContainer.innerHTML = '';
                }}
            }}

            function toggleSummary() {{
                const modal = document.getElementById('summary-modal');
                if (modal.classList.contains('hidden')) {{
                    const now = new Date();
                    dashboardMonth = now.getFullYear() + '-' + String(now.getMonth() + 1).padStart(2, '0');
                    calculateSummary(dashboardMonth);
                    showSummaryView();
                    modal.classList.remove('hidden');
                    modal.classList.add('flex');
                }} else {{
                    modal.classList.add('hidden');
                    modal.classList.remove('flex');
                }}
            }}

            function calculateSummary(monthPrefix) {{
                if (monthPrefix) dashboardMonth = monthPrefix;
                const cache = getCache();

                const companyData = {{}};
                let totalItems = 0;

                Object.keys(cache).forEach(dateKey => {{
                    if (dateKey.startsWith(dashboardMonth)) {{
                        cache[dateKey].forEach(item => {{
                            if (item.is_link_only || item.is_error) return;
                            const name = item.company_name;
                            if (!companyData[name]) {{
                                companyData[name] = {{ count: 0, dates: new Set(), badgeColor: item.badge_color }};
                            }}
                            companyData[name].count++;
                            companyData[name].dates.add(item.date);
                            totalItems++;
                        }});
                    }}
                }});

                const sorted = Object.entries(companyData).sort((a, b) => b[1].count - a[1].count);
                const list = document.getElementById('summary-list');
                const totalEl = document.getElementById('summary-total');
                const monthEl = document.getElementById('summary-month');

                monthEl.textContent = dashboardMonth;
                totalEl.textContent = totalItems;

                if (sorted.length === 0) {{
                    list.innerHTML = '<div class="text-center text-slate-400 py-10"><i class="fas fa-inbox text-3xl mb-3 block opacity-30"></i>この月のデータはありません</div>';
                    return;
                }}

                const maxCount = sorted[0][1].count;

                list.innerHTML = sorted.map(([name, data], index) => {{
                    const percent = (data.count / maxCount) * 100;
                    const dateList = Array.from(data.dates)
                        .map(d => parseInt(d.split('-')[2]))
                        .sort((a, b) => a - b)
                        .map(d => String(d).padStart(2, '0'))
                        .join(', ');

                    const badgeColor = data.badgeColor || "#cbd5e1";

                    return `
                    <div class="mb-3 cursor-pointer hover:bg-blue-50 rounded-xl p-3 -mx-3 transition-all group border border-transparent hover:border-blue-200 hover:shadow-sm" onclick="showCompanyDetail(decodeURIComponent('${{encodeURIComponent(name)}}'), '${{badgeColor}}')">
                        <div class="flex justify-between text-sm font-bold text-slate-700 mb-1">
                            <span class="flex items-center">
                                <span class="w-3 h-3 rounded-full mr-2" style="background-color: ${{badgeColor}}"></span>
                                ${{index + 1}}. ${{name}}
                            </span>
                            <span class="flex items-center text-blue-500">
                                ${{data.count}}件
                                <i class="fas fa-chevron-right ml-2 text-sm"></i>
                            </span>
                        </div>
                        <div class="w-full bg-slate-100 rounded-full h-2.5 mb-1">
                            <div class="bg-blue-500 h-2.5 rounded-full transition-all duration-500" style="width: ${{percent}}%"></div>
                        </div>
                        <div class="text-[10px] text-slate-400 font-mono pl-5">
                            <i class="far fa-clock mr-1"></i>Updates: ${{dateList}}
                        </div>
                    </div>
                    `;
                }}).join('');
            }}

            function shiftDashboardMonth(amount) {{
                const parts = dashboardMonth.split('-');
                const d = new Date(parseInt(parts[0]), parseInt(parts[1]) - 1 + amount, 1);
                dashboardMonth = d.getFullYear() + '-' + String(d.getMonth() + 1).padStart(2, '0');
                calculateSummary(dashboardMonth);
                showSummaryView();
            }}

            function showSummaryView() {{
                document.getElementById('dashboard-summary-view').classList.remove('hidden');
                document.getElementById('dashboard-detail-view').classList.add('hidden');
            }}

            function showCompanyDetail(companyName, badgeColor) {{
                const cache = getCache();
                const items = [];
                Object.keys(cache).forEach(dateKey => {{
                    if (dateKey.startsWith(dashboardMonth)) {{
                        cache[dateKey].forEach(item => {{
                            if (item.company_name === companyName && !item.is_link_only && !item.is_error) {{
                                items.push(item);
                            }}
                        }});
                    }}
                }});
                items.sort((a, b) => new Date(a.date) - new Date(b.date));

                document.getElementById('detail-company-name').textContent = companyName;
                document.getElementById('detail-company-badge').style.backgroundColor = badgeColor;
                document.getElementById('detail-month-display').textContent = dashboardMonth;
                document.getElementById('detail-count').textContent = items.length + '件';

                const list = document.getElementById('detail-news-list');
                if (items.length === 0) {{
                    list.innerHTML = '<div class="text-center text-slate-400 py-10"><i class="fas fa-inbox text-3xl mb-3 block opacity-30"></i>この月のニュースはありません</div>';
                }} else {{
                    list.innerHTML = items.map(item => {{
                        return `
                        <a href="${{item.url}}" target="_blank" class="block p-4 bg-white border border-slate-200 rounded-xl hover:border-blue-300 hover:shadow-md transition-all group">
                            <div class="flex items-center justify-between mb-2">
                                <span class="text-xs font-bold text-slate-400 bg-slate-100 px-2.5 py-1 rounded-full">
                                    <i class="far fa-calendar-alt mr-1"></i>${{item.date}}
                                </span>
                                <i class="fas fa-external-link-alt text-slate-300 group-hover:text-blue-500 transition-colors"></i>
                            </div>
                            <h4 class="text-sm font-bold text-slate-700 group-hover:text-blue-600 transition-colors leading-relaxed">
                                ${{item.title}}
                            </h4>
                        </a>`;
                    }}).join('');
                }}

                document.getElementById('dashboard-summary-view').classList.add('hidden');
                document.getElementById('dashboard-detail-view').classList.remove('hidden');
            }}
        </script>
    </head>
    <body class="h-full text-slate-900 relative">
        <div id="loading-overlay" class="fixed inset-0 bg-slate-900/50 backdrop-blur-sm z-50 hidden items-center justify-center">
            <div class="bg-white p-8 rounded-2xl shadow-2xl flex flex-col items-center animate-bounce-slow">
                <div class="loader mb-4"></div>
                <p class="text-slate-700 font-bold animate-pulse">Collecting News...</p>
            </div>
        </div>

        <div id="summary-modal" class="fixed inset-0 bg-slate-900/60 backdrop-blur-sm z-50 hidden items-center justify-center p-4" onclick="if(event.target === this) toggleSummary()">
            <div class="bg-white w-full max-w-lg rounded-2xl shadow-2xl overflow-hidden">

                <!-- Summary View -->
                <div id="dashboard-summary-view">
                    <div class="p-5 bg-slate-50 border-b border-slate-200 flex justify-between items-center">
                        <div>
                            <h3 class="text-xl font-black text-slate-800"><i class="fas fa-chart-bar mr-2 text-blue-500"></i>Monthly Report</h3>
                            <div class="flex items-center mt-2 bg-white border border-slate-200 rounded-lg shadow-sm">
                                <button onclick="shiftDashboardMonth(-1)" class="px-3 py-1.5 text-blue-600 hover:bg-blue-50 rounded-l-lg transition-colors font-bold text-sm"><i class="fas fa-chevron-left mr-1"></i>前月</button>
                                <p class="text-sm text-slate-800 font-black tracking-wider px-3 py-1.5 border-x border-slate-200 min-w-[6rem] text-center" id="summary-month">YYYY-MM</p>
                                <button onclick="shiftDashboardMonth(1)" class="px-3 py-1.5 text-blue-600 hover:bg-blue-50 rounded-r-lg transition-colors font-bold text-sm">次月<i class="fas fa-chevron-right ml-1"></i></button>
                            </div>
                        </div>
                        <button onclick="toggleSummary()" class="text-slate-400 hover:text-slate-600 transition-colors"><i class="fas fa-times text-2xl"></i></button>
                    </div>
                    <div id="summary-scroll-area" class="p-6">
                        <div class="flex items-center justify-center mb-8">
                            <div class="text-center">
                                <span class="block text-4xl font-black text-blue-600" id="summary-total">0</span>
                                <span class="text-xs font-bold text-slate-400 uppercase tracking-widest">Total News</span>
                            </div>
                        </div>
                        <div id="summary-list"></div>
                    </div>
                    <div class="p-4 bg-slate-50 border-t border-slate-200 text-center">
                        <p class="text-xs text-slate-400">Based on collected cache data</p>
                    </div>
                </div>

                <!-- Detail View (hidden by default) -->
                <div id="dashboard-detail-view" class="hidden">
                    <div class="p-5 bg-slate-50 border-b border-slate-200">
                        <div class="flex items-center justify-between">
                            <button onclick="showSummaryView()" class="text-blue-500 hover:text-blue-700 transition-colors text-sm font-bold">
                                <i class="fas fa-arrow-left mr-1"></i>戻る
                            </button>
                            <button onclick="toggleSummary()" class="text-slate-400 hover:text-slate-600 transition-colors"><i class="fas fa-times text-2xl"></i></button>
                        </div>
                        <div class="flex items-center mt-3">
                            <span id="detail-company-badge" class="w-4 h-4 rounded-full mr-3 shadow-sm"></span>
                            <h3 class="text-lg font-black text-slate-800" id="detail-company-name">Company</h3>
                        </div>
                        <div class="flex items-center justify-between mt-1">
                            <p class="text-xs text-slate-500 font-bold" id="detail-month-display">YYYY-MM</p>
                            <span class="text-xs font-bold text-blue-600" id="detail-count">0件</span>
                        </div>
                    </div>
                    <div class="p-4 space-y-3" id="detail-news-list"></div>
                </div>

            </div>
        </div>

        <div class="flex h-full">
            <aside class="w-80 bg-white border-r border-slate-200 overflow-y-auto flex flex-col shadow-sm z-20">
                <div class="p-6 bg-slate-900 text-white sticky top-0 z-10">
                    <h1 class="text-2xl font-black tracking-tighter flex items-center"><i class="fas fa-bolt mr-3 text-yellow-400"></i>NEWS SCOUT</h1>
                    <p class="text-slate-400 text-xs mt-1 font-medium tracking-widest">RETAIL INTELLIGENCE</p>
                </div>
                
                <div class="px-6 pt-6">
                    <button onclick="toggleSummary()" class="w-full py-3 bg-gradient-to-r from-indigo-500 to-blue-600 text-white font-bold rounded-xl shadow-md hover:shadow-lg hover:scale-[1.02] transition-all flex items-center justify-center">
                        <i class="fas fa-chart-pie mr-2"></i>View Dashboard
                    </button>
                </div>

                <form id="searchForm" action="/" method="get" class="flex-1 p-6 space-y-8 flex flex-col">
                    <div>
                        <label class="block text-xs font-black text-slate-400 uppercase tracking-widest mb-3">Date Range</label>
                        <div class="space-y-2">
                            <div class="flex items-center gap-2">
                                <span class="text-xs font-bold text-slate-500 w-8">From</span>
                                <input type="date" id="startDateInput" name="start_date" value="{start_date_str}" class="flex-1 border-2 border-slate-200 rounded-xl p-2.5 font-bold text-slate-700 text-sm focus:border-blue-500 focus:ring-2 focus:ring-blue-200 outline-none transition-all shadow-sm">
                            </div>
                            <div class="flex items-center gap-2">
                                <span class="text-xs font-bold text-slate-500 w-8">To</span>
                                <input type="date" id="endDateInput" name="end_date" value="{end_date_str}" class="flex-1 border-2 border-slate-200 rounded-xl p-2.5 font-bold text-slate-700 text-sm focus:border-blue-500 focus:ring-2 focus:ring-blue-200 outline-none transition-all shadow-sm">
                            </div>
                        </div>
                        <div class="flex items-center gap-2 mt-3">
                            <button type="button" onclick="shiftRange(-1)" class="flex-1 py-2 bg-white border border-slate-200 rounded-lg hover:bg-slate-50 text-slate-600 shadow-sm transition-all active:scale-95"><i class="fas fa-chevron-left"></i></button>
                            <button type="button" onclick="setQuickRange('today')" class="px-3 py-2 bg-slate-100 text-slate-600 rounded-lg text-xs font-bold hover:bg-slate-200 transition-colors">Today</button>
                            <button type="button" onclick="setQuickRange('week')" class="px-3 py-2 bg-slate-100 text-slate-600 rounded-lg text-xs font-bold hover:bg-slate-200 transition-colors">1W</button>
                            <button type="button" onclick="setQuickRange('month')" class="px-3 py-2 bg-slate-100 text-slate-600 rounded-lg text-xs font-bold hover:bg-slate-200 transition-colors">1M</button>
                            <button type="button" onclick="shiftRange(1)" class="flex-1 py-2 bg-white border border-slate-200 rounded-lg hover:bg-slate-50 text-slate-600 shadow-sm transition-all active:scale-95"><i class="fas fa-chevron-right"></i></button>
                        </div>
                    </div>

                    <div class="mt-6 mb-2">
                        <button type="submit" class="w-full bg-slate-800 text-white font-black py-4 rounded-xl shadow-lg hover:bg-slate-700 hover:shadow-xl hover:scale-[1.02] active:scale-95 transition-all duration-200 ease-out flex items-center justify-center">
                            <i class="fas fa-search mr-2"></i>SEARCH NEWS
                        </button>
                    </div>

                    <div class="flex-1 overflow-y-auto -mx-2 px-2">
                        <label class="block text-xs font-black text-slate-400 uppercase tracking-widest mb-3 sticky top-0 bg-white py-2 z-10">Categories</label>
                        {sidebar_html}
                    </div>
                </form>
            </aside>
            <main class="flex-1 p-10 overflow-y-auto bg-slate-50">
                <div class="max-w-6xl mx-auto">
                    <div class="mb-4">
                        <div class="relative mb-4">
                            <i class="fas fa-search absolute left-4 top-3.5 text-slate-400"></i>
                            <input type="text" id="keywordInput" placeholder="キーワードで絞り込み (例: いちご, カレー, 値上げ)" class="w-full pl-11 pr-4 py-3 bg-white border border-slate-200 rounded-xl shadow-sm focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent transition-all">
                        </div>

                        <div class="flex flex-wrap gap-2">
                            <button onclick="filterNews('category', 'all')" id="btn-all" class="filter-btn active px-4 py-2 bg-white border border-slate-200 rounded-full text-sm font-bold text-slate-600 hover:bg-slate-50 transition-colors shadow-sm">All</button>
                            <button onclick="filterNews('category', 'product')" id="btn-product" class="filter-btn px-4 py-2 bg-white border border-slate-200 rounded-full text-sm font-bold text-slate-600 hover:bg-slate-50 transition-colors shadow-sm">🎁 商品・販促</button>
                            <button onclick="filterNews('category', 'csr')" id="btn-csr" class="filter-btn px-4 py-2 bg-white border border-slate-200 rounded-full text-sm font-bold text-slate-600 hover:bg-slate-50 transition-colors shadow-sm">🌿 環境・社会</button>
                            <button onclick="filterNews('category', 'corporate')" id="btn-corporate" class="filter-btn px-4 py-2 bg-white border border-slate-200 rounded-full text-sm font-bold text-slate-600 hover:bg-slate-50 transition-colors shadow-sm">🏢 経営・人事</button>
                            <button onclick="filterNews('category', 'store')" id="btn-store" class="filter-btn px-4 py-2 bg-white border border-slate-200 rounded-full text-sm font-bold text-slate-600 hover:bg-slate-50 transition-colors shadow-sm">🏪 店舗・地域</button>
                            <button onclick="filterNews('category', 'dx')" id="btn-dx" class="filter-btn px-4 py-2 bg-white border border-slate-200 rounded-full text-sm font-bold text-slate-600 hover:bg-slate-50 transition-colors shadow-sm">📱 DX・デジタル</button>
                        </div>
                    </div>

                    <div class="mb-10 pb-4 border-b border-slate-200 flex justify-between items-end">
                        <div>
                            <h2 class="text-3xl font-black text-slate-900 tracking-tight">Search Results</h2>
                            <div class="flex items-center mt-2 text-slate-500 font-medium">
                                <i class="far fa-clock mr-2"></i>
                                <span id="display-date-str">Range: {start_date_str} ~ {end_date_str}</span>
                            </div>
                        </div>
                        <span id="result-count" class="bg-blue-100 text-blue-700 font-bold px-4 py-2 rounded-full text-sm shadow-sm">Loading...</span>
                    </div>
                    
                    <div id="result-grid" class="grid grid-cols-1 lg:grid-cols-2 xl:grid-cols-3 gap-6"></div>
                    
                    <div id="link-only-container" class="mt-8 mb-6 grid grid-cols-1 gap-2 hidden"></div>
                    
                    <div id="empty-message" class="col-span-full text-center py-24 text-slate-400 hidden">
                        <i class="fas fa-search mb-6 text-5xl block opacity-30"></i>
                        <p class="text-xl font-bold">まだデータがありません</p>
                        <p class="mt-2 text-sm">「SEARCH NEWS」ボタンを押して収集を開始してください</p>
                    </div>
                    
                    {debug_section}
                </div>
            </main>
        </div>
    </body>
    </html>
    """