import os
import re
import unicodedata
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from urllib.parse import urljoin, urlparse, urlunparse
import requests
from bs4 import BeautifulSoup

# companies.py から設定を読み込む
from .companies import COMPANIES

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

# 同時に張る接続数の上限(相手サイトはすべて別ドメインなので各サイトへは1接続)。
# 同時並列数が多いほどピーク時のメモリ使用量が増える(小さいホスティング環境では
# メモリ超過の原因になりうる)ため、環境変数 NEWS_FETCH_MAX_WORKERS で調整可能にしている。
# 空文字・数値でない値は既定値5にフォールバックし、0以下の値は1に切り上げる
# (不正な設定値でアプリの起動やスクレイピング自体が失敗しないようにするため)
def _parse_fetch_max_workers():
    raw = os.environ.get("NEWS_FETCH_MAX_WORKERS", "5")
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return 5
    return max(1, value)


FETCH_MAX_WORKERS = _parse_fetch_max_workers()

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

        # 各社の取得結果ステータス。呼び出し側(キャッシュ層など)が参照できるよう
        # インスタンス属性として記録する: {company_id: (status, status_code)}
        self.last_status = {}

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
                    self.last_status[cid] = ("404", 404)
                    continue
                elif resp.status_code == 403:
                    debug_logs.append("Status 403 (Access Denied). Fallback to link.")
                    all_items.append(self._fallback_item(company, start_date_str, 403))
                    self.last_status[cid] = ("403", 403)
                    continue
                elif resp.status_code != 200:
                    debug_logs.append(f"Error Status: {resp.status_code}")
                    all_items.append(self._fallback_item(company, start_date_str, resp.status_code))
                    self.last_status[cid] = ("error", resp.status_code)
                    continue
                else:
                    html_content = resp.text

                soup = BeautifulSoup(html_content, "html.parser")

            except Exception as exc:
                debug_logs.append(f"Exception: {exc}")
                all_items.append(self._fallback_item(company, start_date_str))
                self.last_status[cid] = ("exception", None)
                continue

            self.last_status[cid] = ("ok", 200)
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
                # (url, date, title) で重複判定する。入れ子要素(例: li の中の div)が
                # 同じ記事を二重に拾うのを防ぎつつ、統計ページ等の「同じURLに日付違いの
                # お知らせが複数リンクする」ケースを別記事として残すため、url 単独ではなく
                # 日付・タイトルまで含めたキーにしている
                processed_keys = set()

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

                            dedup_key = (url, found_date_str, title)
                            if dedup_key not in processed_keys:
                                all_items.append({
                                    "company_name": company["name"],
                                    "badge_color": company["badge_color"],
                                    "title": title[:100] + "..." if len(title) > 100 else title,
                                    "url": url,
                                    "date": found_date_str,
                                    "is_link_only": False,
                                    "is_error": False
                                })
                                processed_keys.add(dedup_key)
                                found_count += 1
                                debug_logs.append(f"  -> Found: {title[:15]}...")
                                # あえて break しない（同じ日に複数ニュースがある場合のため）

            if found_count == 0:
                debug_logs.append("Result: 0 items found.")

        return all_items, debug_logs, checked_company_names
