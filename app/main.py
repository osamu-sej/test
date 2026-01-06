import json
import re
import unicodedata
from datetime import datetime, timedelta
from urllib.parse import urljoin, urlparse, urlunparse
import time
import requests
from bs4 import BeautifulSoup
from fastapi import FastAPI, Query
from fastapi.responses import HTMLResponse

# companies.py から設定を読み込む
from .companies import COMPANIES

app = FastAPI(title="Retail News Scout")

# ==========================================
#  スクレイピングロジック (NewsScraper)
# ==========================================
class NewsScraper:
    def __init__(self) -> None:
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7",
            "Accept-Language": "ja,en-US;q=0.9,en;q=0.8",
            "Referer": "https://www.google.com/",
            "Connection": "keep-alive"
        })

    def _fallback_item(self, company, target_date_str, status_code=None):
        if status_code == 403:
            title = "🔒 公式サイトで最新ニュースを確認する"
            badge_color = "#3b82f6" 
            is_link_only = True
        elif status_code == 404:
            title = "【404】ページが見つかりません"
            badge_color = company["badge_color"]
            is_link_only = False
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

    def fetch_news(self, company_ids, target_date_str):
        target_date = datetime.strptime(target_date_str, "%Y-%m-%d")
        all_items = []
        debug_logs = []
        
        checked_company_names = []

        for cid in company_ids:
            company = next((c for c in COMPANIES if c["id"] == cid), None)
            if not company: continue
            
            checked_company_names.append(company["name"])
            debug_logs.append(f"--- Checking {company['name']} ---")

            # 強制リンクモードの企業
            if company.get("scraper_type") == "force_link":
                all_items.append({
                    "company_name": company["name"],
                    "badge_color": "#3b82f6",
                    "title": "👉 公式サイトで最新ニュースを見る",
                    "url": company["url"],
                    "date": target_date_str,
                    "is_link_only": True,
                    "is_error": False
                })
                continue

            html_content = None
            
            try:
                resp = self.session.get(company["url"], timeout=10.0)
                resp.encoding = resp.apparent_encoding
                
                if resp.status_code == 403:
                    debug_logs.append("Status 403 (Access Denied). Fallback to link.")
                    all_items.append(self._fallback_item(company, target_date_str, 403))
                    continue

                elif resp.status_code != 200:
                    debug_logs.append(f"Error Status: {resp.status_code}")
                    all_items.append(self._fallback_item(company, target_date_str, resp.status_code))
                    continue
                else:
                    html_content = resp.text

                soup = BeautifulSoup(html_content, "html.parser")
                
            except Exception as exc:
                debug_logs.append(f"Exception: {exc}")
                all_items.append(self._fallback_item(company, target_date_str))
                continue

            found_count = 0
            
            # ==========================================
            #  ここから専用ロジックエリア
            # ==========================================

            # --- ライフ専用ロジック ---
            if company["id"] == "life":
                life_dates = soup.find_all(string=re.compile(r"20\d{2}/\d{1,2}/\d{1,2}"))
                candidates_map = {} 

                for date_node in life_dates:
                    try:
                        date_text = date_node.strip()
                        y, m, d = re.split(r"[/]", date_text)
                        found_date_str = f"{y}-{int(m):02d}-{int(d):02d}"
                        
                        if found_date_str == target_date_str:
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
                            clean_card_text = re.sub(r'\s+', ' ', card_full_text).strip()
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

            # --- セブン＆アイ専用ロジック (現状維持) ---
            # いったん深追いせず、安定動作していた頃のロジックに戻しています
            elif company["id"] in ["seven_2026", "seven_2025"]:
                seven_target_tags = soup.find_all(['dt', 'dd', 'li', 'div', 'p'])
                seven_processed_urls = set()
                
                for element in seven_target_tags:
                    full_text = unicodedata.normalize("NFKC", element.get_text(" ", strip=True))
                    match = re.search(r"(\d{4})\s*[./年]\s*(\d{1,2})\s*[./月]\s*(\d{1,2})", full_text)
                    if not match: continue
                    y, m, d = match.groups()
                    found_date_str = f"{y}-{int(m):02d}-{int(d):02d}"
                    
                    if found_date_str == target_date_str:
                        link_tag = element.find('a', href=True)
                        if not link_tag and element.name == 'dt':
                            dd = element.find_next_sibling('dd')
                            if dd: link_tag = dd.find('a', href=True)
                        if not link_tag and element.parent:
                            link_tag = element.parent.find('a', href=True)

                        if link_tag and link_tag.get("href"):
                            url = urljoin(company["url"], link_tag["href"])
                            title = link_tag.get_text(strip=True)
                            if not title and link_tag.parent:
                                title = link_tag.parent.get_text(" ", strip=True).replace(full_text, "").strip()
                            
                            if url not in seven_processed_urls:
                                all_items.append({
                                    "company_name": company["name"],
                                    "badge_color": company["badge_color"],
                                    "title": title[:100] + "..." if len(title) > 100 else title,
                                    "url": url,
                                    "date": found_date_str,
                                    "is_link_only": False,
                                    "is_error": False
                                })
                                seven_processed_urls.add(url)
                                found_count += 1
                                debug_logs.append(f"  -> Found (7&i Standard): {title[:15]}...")
                
                if found_count > 0:
                    continue

            # --- 汎用ロジック (通常) ---
            if found_count == 0:
                target_tags = soup.find_all(['dt', 'dd', 'li', 'div', 'p', 'span', 'time', 'td', 'tr'])
                processed_urls = set()

                for element in target_tags:
                    full_text = unicodedata.normalize("NFKC", element.get_text(" ", strip=True))
                    if len(full_text) > 500: continue 
                    
                    match = re.search(r"(\d{4})\s*[./年]\s*(\d{1,2})\s*[./月]\s*(\d{1,2})", full_text)
                    if not match: continue
                    y, m, d = match.groups()
                    found_date_str = f"{y}-{int(m):02d}-{int(d):02d}"
                    
                    if found_date_str == target_date_str:
                        if company["id"] == "life": continue 
                        if company["id"] in ["seven_2026", "seven_2025"]: continue

                        debug_logs.append(f"★ MATCH: {found_date_str} in <{element.name}>")
                        link_tag = None
                        
                        dt_node = None
                        if element.name == 'dt': dt_node = element
                        elif element.parent and element.parent.name == 'dt': dt_node = element.parent
                        if dt_node:
                            dd_node = dt_node.find_next_sibling('dd')
                            if dd_node: link_tag = dd_node.find('a', href=True)
                        
                        if not link_tag: link_tag = element.find('a', href=True)
                        
                        if not link_tag:
                            curr = element
                            for _ in range(5):
                                if not curr: break
                                if curr.name == 'a' and curr.has_attr('href'):
                                    link_tag = curr
                                    break
                                if curr.name in ['li', 'tr', 'article', 'td'] or (curr.name=='div' and any(c in str(curr.get('class')) for c in ['item', 'news', 'col', 'block'])):
                                    links = curr.find_all("a", href=True)
                                    valid = [l for l in links if len(l.get_text(strip=True)) > 4]
                                    if valid:
                                        link_tag = max(valid, key=lambda l: len(l.get_text(strip=True)))
                                        break
                                curr = curr.parent
                        
                        if not link_tag: link_tag = element.find_next("a", href=True)

                        if link_tag and link_tag.get("href"):
                            title = link_tag.get_text(strip=True)
                            url = urljoin(company["url"], link_tag["href"])
                            
                            if not title or len(title) < 5:
                                parent_text = element.get_text(" ", strip=True)
                                title = parent_text if len(parent_text) > 5 else "ニュース詳細"

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
                                
                                # ★修正ポイント：ファミマ・ローソン・ミニストップなどは1つ見つけても終了しない！
                                if company["id"] not in ["famima", "lawson", "ministop"]:
                                    break 
            
            if found_count == 0:
                debug_logs.append("Result: 0 items found.")

        return all_items, debug_logs, checked_company_names

# ==========================================
#  UI生成ロジック
# ==========================================
def generate_sidebar_html(selected_ids):
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
async def read_root(date: str = Query(None), companies: list[str] = Query(None)):
    today = datetime.now()
    # 初期状態は全選択
    selected_ids = companies if companies else [c["id"] for c in COMPANIES]
    
    target_date_str = date if date else today.strftime("%Y-%m-%d")

    items, logs, checked_names = NewsScraper().fetch_news(selected_ids, target_date_str)
    
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

            function shiftDate(amount) {{
                const input = document.getElementById('dateInput');
                if(!input.value) return;
                const parts = input.value.split('-');
                const d = new Date(parts[0], parts[1] - 1, parts[2]);
                d.setDate(d.getDate() + amount);
                
                const y = d.getFullYear();
                const m = String(d.getMonth() + 1).padStart(2, '0');
                const day = String(d.getDate()).padStart(2, '0');
                input.value = `${{y}}-${{m}}-${{day}}`;
                renderFromCacheOnly(input.value);
            }}

            document.addEventListener('DOMContentLoaded', function() {{
                const form = document.querySelector('form');
                const loader = document.getElementById('loading-overlay');
                const dateInput = document.getElementById('dateInput');
                const searchInput = document.getElementById('keywordInput');

                if(form && loader) {{
                    form.addEventListener('submit', function() {{
                        loader.classList.remove('hidden');
                        loader.classList.add('flex');
                    }});
                }}
                
                const SERVER_RESULTS = {items_json}; 
                const CHECKED_NAMES = {checked_names_json}; 
                const CURRENT_DATE = "{target_date_str}";
                
                updateCacheAndRender(CURRENT_DATE, SERVER_RESULTS, CHECKED_NAMES);

                dateInput.addEventListener('change', function(e) {{
                    const newDate = e.target.value;
                    renderFromCacheOnly(newDate); 
                }});
                
                searchInput.addEventListener('input', function(e) {{
                    const keyword = e.target.value;
                    filterNews('search', keyword); 
                }});
            }});

            function setDateAndShow(dateStr) {{
                document.getElementById('dateInput').value = dateStr;
                renderFromCacheOnly(dateStr);
            }}

            function updateCacheAndRender(dateKey, newItems, checkedNames) {{
                let cache = getCache();
                let dateItems = cache[dateKey] || [];
                
                if (checkedNames && checkedNames.length > 0) {{
                    const checkedSet = new Set(checkedNames);
                    dateItems = dateItems.filter(item => !checkedSet.has(item.company_name));
                }}

                if (newItems && newItems.length > 0) {{
                    newItems.forEach(item => {{
                        if (!dateItems.some(saved => saved.url === item.url)) {{
                            dateItems.push(item);
                        }}
                    }});
                }}
                
                cache[dateKey] = dateItems;
                localStorage.setItem(STORAGE_KEY, JSON.stringify(cache));
                renderGrid(dateItems, dateKey);
            }}

            function renderFromCacheOnly(dateKey) {{
                let cache = getCache();
                let dateItems = cache[dateKey] || [];
                const kw = document.getElementById('keywordInput').value;
                if(kw) {{
                    filterNews('search', kw);
                }} else {{
                    renderGrid(dateItems, dateKey);
                }}
            }}
            
            function deleteItem(dateKey, url) {{
                let cache = getCache();
                if (cache[dateKey]) {{
                    cache[dateKey] = cache[dateKey].filter(item => item.url !== url);
                    localStorage.setItem(STORAGE_KEY, JSON.stringify(cache));
                    const kw = document.getElementById('keywordInput').value;
                    if(kw) filterNews('search', kw);
                    else renderGrid(cache[dateKey], dateKey);
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

            function filterNews(mode, value) {{
                currentFilterMode = mode;
                const dateKey = document.getElementById('dateInput').value;
                let itemsToDisplay = [];
                const cache = getCache();

                if (mode === 'search') {{
                    currentSearchText = value;
                    if (currentSearchText) {{
                        const currentMonthPrefix = dateKey.substring(0, 7);
                        Object.keys(cache).forEach(key => {{
                            if (key.startsWith(currentMonthPrefix)) {{
                                itemsToDisplay = itemsToDisplay.concat(cache[key]);
                            }}
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
                        itemsToDisplay = cache[dateKey] || [];
                    }}
                }} else if (mode === 'category') {{
                    currentCategory = value;
                    currentSearchText = '';
                    document.getElementById('keywordInput').value = '';
                    document.querySelectorAll('.filter-btn').forEach(btn => btn.classList.remove('active'));
                    document.getElementById('btn-' + value).classList.add('active');
                    itemsToDisplay = cache[dateKey] || [];
                }}
                renderGrid(itemsToDisplay, dateKey);
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

            function renderGrid(items, displayDate) {{
                const gridContainer = document.getElementById('result-grid');
                const linkContainer = document.getElementById('link-only-container');
                const countBadge = document.getElementById('result-count');
                const emptyMsg = document.getElementById('empty-message');
                const dateDisplay = document.getElementById('display-date-str');
                
                if(dateDisplay) dateDisplay.textContent = 'Target: ' + displayDate;
                if (currentFilterMode === 'search' && currentSearchText) {{
                    const currentMonthPrefix = displayDate.substring(0, 7);
                    dateDisplay.textContent = 'Search: ' + currentMonthPrefix + ' (Cached)';
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
                    calculateSummary(); 
                    modal.classList.remove('hidden');
                    modal.classList.add('flex');
                }} else {{
                    modal.classList.add('hidden');
                    modal.classList.remove('flex');
                }}
            }}

            function calculateSummary() {{
                const cache = getCache();
                const now = new Date();
                const currentMonthPrefix = now.getFullYear() + '-' + String(now.getMonth() + 1).padStart(2, '0');
                
                const companyData = {{}};
                let totalItems = 0;

                Object.keys(cache).forEach(dateKey => {{
                    if (dateKey.startsWith(currentMonthPrefix)) {{
                        cache[dateKey].forEach(item => {{
                            // ★ リンクのみ(1行表示)やエラーのものはカウントしない
                            if (item.is_link_only || item.is_error) return;

                            const name = item.company_name;
                            if (!companyData[name]) {{
                                companyData[name] = {{ count: 0, dates: new Set() }};
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
                
                monthEl.textContent = currentMonthPrefix;
                totalEl.textContent = totalItems;

                if (sorted.length === 0) {{
                    list.innerHTML = '<div class="text-center text-slate-400 py-10">No data for this month yet.</div>';
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

                    let badgeColor = "#cbd5e1"; 
                    for (const date in cache) {{
                        const found = cache[date].find(i => i.company_name === name);
                        if (found) {{ badgeColor = found.badge_color; break; }}
                    }}

                    return `
                    <div class="mb-5">
                        <div class="flex justify-between text-sm font-bold text-slate-700 mb-1">
                            <span class="flex items-center">
                                <span class="w-3 h-3 rounded-full mr-2" style="background-color: ${{badgeColor}}"></span>
                                ${{index + 1}}. ${{name}}
                            </span>
                            <span>${{data.count}}件</span>
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
            <div class="bg-white w-full max-w-lg rounded-2xl shadow-2xl overflow-hidden flex flex-col max-h-[90vh]">
                <div class="p-5 bg-slate-50 border-b border-slate-200 flex justify-between items-center">
                    <div>
                        <h3 class="text-xl font-black text-slate-800"><i class="fas fa-chart-bar mr-2 text-blue-500"></i>Monthly Report</h3>
                        <p class="text-xs text-slate-500 font-bold uppercase tracking-wider mt-1" id="summary-month">YYYY-MM</p>
                    </div>
                    <button onclick="toggleSummary()" class="text-slate-400 hover:text-slate-600 transition-colors"><i class="fas fa-times text-2xl"></i></button>
                </div>
                <div class="p-6 overflow-y-auto">
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
                        <label class="block text-xs font-black text-slate-400 uppercase tracking-widest mb-3">Target Date</label>
                        <input type="date" id="dateInput" name="date" value="{target_date_str}" class="w-full border-2 border-slate-200 rounded-xl p-3 font-bold text-slate-700 focus:border-blue-500 focus:ring-2 focus:ring-blue-200 outline-none transition-all shadow-sm mb-3">
                        <div class="flex items-center gap-2">
                            <button type="button" onclick="shiftDate(-1)" class="flex-1 py-2 bg-white border border-slate-200 rounded-lg hover:bg-slate-50 text-slate-600 shadow-sm transition-all active:scale-95"><i class="fas fa-chevron-left"></i></button>
                            <button type="button" onclick="setDateAndShow('{today.strftime('%Y-%m-%d')}')" class="px-4 py-2 bg-slate-100 text-slate-600 rounded-lg text-xs font-bold hover:bg-slate-200 transition-colors">Today</button>
                            <button type="button" onclick="shiftDate(1)" class="flex-1 py-2 bg-white border border-slate-200 rounded-lg hover:bg-slate-50 text-slate-600 shadow-sm transition-all active:scale-95"><i class="fas fa-chevron-right"></i></button>
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
                                <span id="display-date-str">Target: {target_date_str}</span>
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