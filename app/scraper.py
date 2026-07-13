import os
import re
import unicodedata
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from email.utils import parsedate_to_datetime
from urllib.parse import urljoin, urlparse, urlunparse
import requests
from bs4 import BeautifulSoup

# companies.py から設定を読み込む
from .companies import COMPANIES
from .envutil import env_int

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

# 1ページから解析する HTML の上限文字数。巨大ページによるメモリ急騰を防ぐ
MAX_HTML_CHARS = 2_000_000

# 同時に張る接続数の上限(相手サイトはすべて別ドメインなので各サイトへは1接続)。
# 同時並列数が多いほどピーク時のメモリ使用量が増える(小さいホスティング環境では
# メモリ超過の原因になりうる)ため、環境変数 NEWS_FETCH_MAX_WORKERS で調整可能。
# 不正値は既定値5にフォールバックし、0以下は1に切り上げる(envutil.env_int)
FETCH_MAX_WORKERS = env_int("NEWS_FETCH_MAX_WORKERS", 5, minimum=1)

# フィード(RSS/Atom)自動発見の対象となる <link> の type 属性値
FEED_LINK_TYPES = ("application/rss+xml", "application/atom+xml")

# 日付の隣にある「タイトルではないリンク」を拾わないための除外語
SIBLING_LINK_IGNORE = {"一覧を見る", "もっと見る", "詳しくはこちら", "詳細はこちら", "続きを読む", "一覧へ", "READ MORE"}


def _parse_feed_datetime(text):
    """フィードの日時文字列(RFC822 / ISO8601)を datetime にする。失敗時は None。"""
    if not text:
        return None
    text = text.strip()
    try:
        return parsedate_to_datetime(text)  # 例: Mon, 06 Jul 2026 10:00:00 +0900 (RSS)
    except (TypeError, ValueError):
        pass
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00"))  # 例: 2026-07-06T10:00:00+09:00 (Atom)
    except ValueError:
        return None

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

    def _feed_candidates(self, company, soup):
        """この情報源で試すべきフィード URL の候補を返す。
        1. companies.py に rss_url が設定されていればそれを最優先
        2. ページの <head> が宣言している RSS/Atom フィード(自動発見)"""
        candidates = []
        if company.get("rss_url"):
            candidates.append(company["rss_url"])
        if soup is not None:
            for link in soup.find_all("link"):
                rel = link.get("rel") or []
                if isinstance(rel, str):
                    rel = [rel]
                link_type = (link.get("type") or "").lower()
                if "alternate" in [r.lower() for r in rel] and link_type in FEED_LINK_TYPES and link.get("href"):
                    candidates.append(urljoin(company["url"], link["href"]))
        # 順序を保って重複除去し、多くても3つまで
        seen = set()
        unique = []
        for c in candidates:
            if c not in seen:
                seen.add(c)
                unique.append(c)
        return unique[:3]

    def _fetch_feed_items(self, company, feed_url, start_date_str, end_date_str, debug_logs):
        """RSS 2.0 / Atom フィードから期間内の記事を抽出する。失敗しても例外は投げない。"""
        try:
            resp = self.session.get(feed_url, timeout=10.0)
            if resp.status_code != 200:
                debug_logs.append(f"Feed {feed_url}: status {resp.status_code}")
                return []
            root = ET.fromstring(resp.content)
        except Exception as exc:
            debug_logs.append(f"Feed error ({feed_url}): {exc}")
            return []

        items = []
        seen = set()
        for node in root.iter():
            tag = node.tag.split("}")[-1].lower()
            if tag not in ("item", "entry"):
                continue
            title = link = date_text = None
            link_is_alternate = False
            for child in node:
                ctag = child.tag.split("}")[-1].lower()
                if ctag == "title":
                    title = (child.text or "").strip()
                elif ctag == "link":
                    # RSS はテキスト、Atom は href 属性。Atom では1エントリに複数の
                    # <link>(記事本体 / rel="self" / enclosure 等)が並ぶことがあるため、
                    # 記事本体を指す rel="alternate"(rel 省略時は alternate 扱い)を優先し、
                    # 後から来る self や enclosure で上書きしない
                    candidate = (child.text or "").strip() or child.get("href")
                    if not candidate:
                        continue
                    rel = (child.get("rel") or "alternate").lower()
                    if rel == "alternate":
                        if not link_is_alternate:
                            link = candidate
                            link_is_alternate = True
                    elif link is None:
                        link = candidate
                elif ctag in ("pubdate", "published", "date"):
                    date_text = child.text
                elif ctag == "updated" and date_text is None:
                    date_text = child.text
            parsed = _parse_feed_datetime(date_text)
            if not (title and link and parsed):
                continue
            found_date_str = parsed.strftime("%Y-%m-%d")
            if not (start_date_str <= found_date_str <= end_date_str):
                continue
            url = urljoin(feed_url, link.strip())
            key = (url, found_date_str, title)
            if key in seen:
                continue
            seen.add(key)
            items.append({
                "company_name": company["name"],
                "badge_color": company["badge_color"],
                "title": title[:100] + "..." if len(title) > 100 else title,
                "url": url,
                "date": found_date_str,
                "is_link_only": False,
                "is_error": False
            })
        return items

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

        # HTTP取得はバッチ単位で並列実行する(解析・結果の並び・ログは
        # 従来どおり company_ids の順に直列処理するので出力は変わらない)。
        # 以前は全社分のページを一度にメモリへ溜めてから処理していたため、
        # 収集のたびに「全ページの合計サイズ」までメモリ使用量が跳ね上がっていた。
        # バッチ方式では同時に保持するページが最大 FETCH_MAX_WORKERS 件に抑えられ、
        # 小さいホスティング環境でのメモリ制限超過を防ぐ
        fetch_targets = [
            cid for cid in company_ids
            if cid in company_map and company_map[cid].get("scraper_type") != "force_link"
        ]
        prefetched = {}
        next_fetch_idx = 0

        def _ensure_fetched(target_cid):
            nonlocal next_fetch_idx
            while target_cid not in prefetched and next_fetch_idx < len(fetch_targets):
                batch = fetch_targets[next_fetch_idx:next_fetch_idx + FETCH_MAX_WORKERS]
                next_fetch_idx += len(batch)
                with ThreadPoolExecutor(max_workers=min(FETCH_MAX_WORKERS, len(batch))) as pool:
                    for c, result in zip(
                        batch,
                        pool.map(lambda x: self._fetch_one(company_map[x]["url"]), batch),
                    ):
                        prefetched[c] = result

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
                _ensure_fetched(cid)
                # pop で取り出して参照を手放す(処理済みページをメモリに残さない)
                resp = prefetched.pop(cid, None)
                if resp is None:
                    resp = self._fetch_one(company["url"])
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
                    # 異常に大きいページによるメモリ急騰を防ぐ
                    # (通常のニュース一覧ページは数十万文字以内)
                    if len(html_content) > MAX_HTML_CHARS:
                        debug_logs.append(f"Page too large ({len(html_content)} chars). Truncated.")
                        html_content = html_content[:MAX_HTML_CHARS]

                resp = None  # ページ本文の生データはもう不要。参照を切って解放
                soup = BeautifulSoup(html_content, "html.parser")
                html_content = None  # 解析ツリーができたら文字列側も解放

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

                        # 2. 自分自身の中にリンクがあるか。
                        #    「一覧を見る」等の案内リンクは飛ばしてタイトルらしいリンクを優先し、
                        #    有効なリンクが1つもなければ従来どおり最初のリンクを使う
                        #    (リンク文字列が空の画像リンク型サイトを壊さないため)
                        if not link_tag:
                            anchors = element.find_all('a', href=True)
                            if anchors:
                                link_tag = next(
                                    (a for a in anchors
                                     if len(a.get_text(strip=True)) > 4
                                     and a.get_text(strip=True) not in SIBLING_LINK_IGNORE),
                                    anchors[0],
                                )

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

                        # 4. 日付要素の直後の兄弟要素にリンクがあるパターン
                        #    (日付とタイトルが別々の div/p として並ぶレイアウト。省庁サイト等に多い)
                        if not link_tag:
                            sibling = element.find_next_sibling()
                            hops = 0
                            while sibling is not None and hops < 3:
                                sib_text = unicodedata.normalize("NFKC", sibling.get_text(" ", strip=True))
                                # 兄弟に別の日付があれば次の行に入ったとみなして打ち切り
                                if DATE_FLEX_FINDALL_RE.search(sib_text):
                                    break
                                cand = sibling if (sibling.name == "a" and sibling.has_attr("href")) else sibling.find("a", href=True)
                                if cand is not None:
                                    cand_text = cand.get_text(strip=True)
                                    if len(cand_text) > 4 and cand_text not in SIBLING_LINK_IGNORE:
                                        link_tag = cand
                                        break
                                sibling = sibling.find_next_sibling()
                                hops += 1

                        if not link_tag:
                            debug_logs.append("  (date matched but no link found nearby)")

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

            # --- フィード(RSS/Atom)フォールバック ---
            # HTML からの抽出が0件だった場合、設定済みの rss_url またはページが
            # <head> で宣言しているフィードを自動発見して読む。サイトの見た目
            # (HTML 構造)が変わってもフィードは安定しているため、自己修復として機能する
            if found_count == 0:
                for feed_url in self._feed_candidates(company, soup):
                    feed_items = self._fetch_feed_items(company, feed_url, start_date_str, end_date_str, debug_logs)
                    if feed_items:
                        all_items.extend(feed_items)
                        found_count += len(feed_items)
                        debug_logs.append(f"  -> Feed fallback: {len(feed_items)} items from {feed_url}")
                        break

            # 解析ツリーを明示的に解放する。BeautifulSoup のツリーは循環参照を
            # 含むため、放置すると GC が回るまでメモリに残り続ける
            soup.decompose()

            if found_count == 0:
                debug_logs.append("Result: 0 items found.")

        return all_items, debug_logs, checked_company_names
