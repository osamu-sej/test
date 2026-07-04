function toggleCategory(source, cls) {
    document.querySelectorAll('.' + cls).forEach(el => el.checked = source.checked);
}

const STORAGE_KEY = 'retail_news_date_cache_v1';
const BOOKMARK_KEY = 'retail_news_bookmarks_v1';
const READ_KEY = 'retail_news_read_v1';

// 「NEW」バッジの表示期間(このブラウザで初めて見つけてから24時間)
const NEW_BADGE_MS = 24 * 60 * 60 * 1000;

// 直近 renderGrid で表示した(フィルタ適用後の)項目。CSV エクスポートが使う
let lastRenderedItems = [];

// ===== サイドバー開閉(モバイル用) =====
const SIDEBAR_MOBILE_OPEN = ['flex', 'fixed', 'inset-y-0', 'left-0', 'z-40', 'shadow-2xl'];
function toggleSidebar() {
    const sb = document.getElementById('sidebar');
    if (!sb) return;
    if (sb.classList.contains('fixed')) {
        sb.classList.remove(...SIDEBAR_MOBILE_OPEN);
        sb.classList.add('hidden');
    } else {
        sb.classList.remove('hidden');
        sb.classList.add(...SIDEBAR_MOBILE_OPEN);
    }
}

// ===== ブックマーク・既読 =====
function getBookmarks() {
    const data = localStorage.getItem(BOOKMARK_KEY);
    return data ? JSON.parse(data) : {};
}

function isBookmarked(url) {
    return !!getBookmarks()[url];
}

function toggleBookmark(url) {
    const bookmarks = getBookmarks();
    if (bookmarks[url]) {
        delete bookmarks[url];
    } else {
        const item = lastRenderedItems.find(i => i.url === url) ||
            Object.values(getCache()).flat().find(i => i.url === url);
        if (!item) return;
        bookmarks[url] = {
            company_name: item.company_name,
            badge_color: item.badge_color,
            title: item.title,
            url: item.url,
            date: item.date,
            is_link_only: false,
            is_error: false,
            added_at: Date.now(),
        };
    }
    localStorage.setItem(BOOKMARK_KEY, JSON.stringify(bookmarks));
    updateBookmarkBadge();
    // 現在の表示を維持したまま再描画(ブックマーク表示中なら一覧から消える)
    if (currentFilterMode === 'bookmarks') {
        filterNews('bookmarks', '');
    } else {
        renderGrid(lastRenderedSource, ...Object.values(getDateRange()));
    }
}

function updateBookmarkBadge() {
    const badge = document.getElementById('bookmark-count');
    if (!badge) return;
    const count = Object.keys(getBookmarks()).length;
    badge.textContent = count;
    badge.classList.toggle('hidden', count === 0);
}

function getReadSet() {
    const data = localStorage.getItem(READ_KEY);
    return data ? JSON.parse(data) : {};
}

function markRead(el, url) {
    const read = getReadSet();
    if (!read[url]) {
        read[url] = Date.now();
        localStorage.setItem(READ_KEY, JSON.stringify(read));
    }
    const card = el.closest('.news-card');
    if (card) card.classList.add('opacity-55');
    // 未読のみ表示中は、開いた記事を一覧から外す(新規タブへの遷移を妨げないよう少し遅らせる)
    if (currentFilterMode === 'unread') {
        setTimeout(() => {
            if (currentFilterMode === 'unread') filterNews('unread', '');
        }, 200);
    }
}

// ===== CSV エクスポート(表示中の項目) =====
function exportCsv() {
    const items = lastRenderedItems || [];
    if (!items.length) {
        alert('エクスポートする表示中のニュースがありません。');
        return;
    }
    const categories = window.COMPANY_CATEGORIES || {};
    const bookmarks = getBookmarks();
    const readSet = getReadSet();
    const q = v => '"' + String(v ?? '').replace(/"/g, '""') + '"';
    const rows = [['日付', '企業', '業態', '分類', 'タイトル', 'URL', 'ブックマーク', '既読'].map(q).join(',')];
    items.forEach(i => rows.push([
        q(i.date),
        q(i.company_name),
        q(categories[i.company_name] || ''),
        q(classifyTopics(i.title)),
        q(i.title),
        q(i.url),
        q(bookmarks[i.url] ? '★' : ''),
        q(readSet[i.url] ? '既読' : ''),
    ].join(',')));
    // 先頭の BOM で Excel でも文字化けせずに開ける
    const blob = new Blob(['\uFEFF' + rows.join('\r\n')], { type: 'text/csv;charset=utf-8;' });
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    const { startDate, endDate } = getDateRange();
    a.download = `retail_news_${startDate}_${endDate}.csv`;
    a.click();
    URL.revokeObjectURL(a.href);
}

// renderGrid に渡された(フィルタ前の)元データ。ブックマーク切替後の再描画に使う
let lastRenderedSource = [];

// スクレイピングで取得した外部由来のテキストを innerHTML に入れる前のエスケープ
function esc(s) {
    return String(s ?? '')
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#39;');
}

function getCache() {
    const data = localStorage.getItem(STORAGE_KEY);
    return data ? JSON.parse(data) : {};
}

function formatDate(d) {
    const y = d.getFullYear();
    const m = String(d.getMonth() + 1).padStart(2, '0');
    const day = String(d.getDate()).padStart(2, '0');
    return `${y}-${m}-${day}`;
}

function parseDate(str) {
    const parts = str.split('-');
    return new Date(parseInt(parts[0]), parseInt(parts[1]) - 1, parseInt(parts[2]));
}

function shiftRange(amount) {
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
}

function setQuickRange(mode) {
    const today = new Date();
    const todayStr = formatDate(today);
    const startInput = document.getElementById('startDateInput');
    const endInput = document.getElementById('endDateInput');
    if (mode === 'today') {
        startInput.value = todayStr;
        endInput.value = todayStr;
    } else if (mode === 'week') {
        const weekAgo = new Date(today);
        weekAgo.setDate(weekAgo.getDate() - 6);
        startInput.value = formatDate(weekAgo);
        endInput.value = todayStr;
    } else if (mode === 'month') {
        const monthAgo = new Date(today);
        monthAgo.setDate(monthAgo.getDate() - 29);
        startInput.value = formatDate(monthAgo);
        endInput.value = todayStr;
    }
    renderFromCacheRange();
}

document.addEventListener('DOMContentLoaded', function() {
    const form = document.querySelector('form');
    const loader = document.getElementById('loading-overlay');
    const startInput = document.getElementById('startDateInput');
    const endInput = document.getElementById('endDateInput');
    const searchInput = document.getElementById('keywordInput');

    if(form && loader) {
        form.addEventListener('submit', function() {
            loader.classList.remove('hidden');
            loader.classList.add('flex');
        });
    }

    const SERVER_RESULTS = window.SERVER_RESULTS || [];
    const CHECKED_NAMES = window.CHECKED_NAMES || [];
    const START_DATE = window.START_DATE;
    const END_DATE = window.END_DATE;

    updateCacheAndRender(START_DATE, END_DATE, SERVER_RESULTS, CHECKED_NAMES);
    updateBookmarkBadge();

    startInput.addEventListener('change', function() { renderFromCacheRange(); });
    endInput.addEventListener('change', function() { renderFromCacheRange(); });

    searchInput.addEventListener('input', function(e) {
        const keyword = e.target.value;
        filterNews('search', keyword);
    });

    // AI 質問: Enter で送信(IME 変換確定の Enter は無視)
    const askInput = document.getElementById('ask-input');
    if (askInput) {
        askInput.addEventListener('keydown', function(e) {
            if (e.key === 'Enter' && !e.isComposing) askAi();
        });
    }

    // キーボードショートカット: / でキーワード欄へ、Esc でモーダルを閉じる/絞り込み解除
    document.addEventListener('keydown', function(e) {
        const tag = (document.activeElement && document.activeElement.tagName) || '';
        const typing = tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT';
        if (e.key === '/' && !typing) {
            e.preventDefault();
            searchInput.focus();
        } else if (e.key === 'Escape') {
            const digestModal = document.getElementById('digest-modal');
            const summaryModal = document.getElementById('summary-modal');
            if (digestModal && !digestModal.classList.contains('hidden')) {
                toggleAiDigest();
            } else if (summaryModal && !summaryModal.classList.contains('hidden')) {
                toggleSummary();
            } else if (document.activeElement === searchInput && searchInput.value) {
                searchInput.value = '';
                filterNews('search', '');
            }
        }
    });

    // メイン領域のスクロールで「上へ戻る」ボタンを表示
    const main = document.querySelector('main');
    const topBtn = document.getElementById('scroll-top-btn');
    if (main && topBtn) {
        main.addEventListener('scroll', function() {
            topBtn.classList.toggle('hidden', main.scrollTop < 400);
        });
    }
});

function scrollToTop() {
    const main = document.querySelector('main');
    if (main) main.scrollTo({ top: 0, behavior: 'smooth' });
}

function updateCacheAndRender(startDate, endDate, newItems, checkedNames) {
    let cache = getCache();

    // Group new items by their date
    const byDate = {};
    if (newItems && newItems.length > 0) {
        newItems.forEach(item => {
            const dk = item.date || startDate;
            if (!byDate[dk]) byDate[dk] = [];
            byDate[dk].push(item);
        });
    }

    // Update cache for each date that has new items
    const checkedSet = (checkedNames && checkedNames.length > 0) ? new Set(checkedNames) : null;

    // For dates in range, clear checked companies and merge new items
    const s = parseDate(startDate);
    const e = parseDate(endDate);
    for (let d = new Date(s); d <= e; d.setDate(d.getDate() + 1)) {
        const dk = formatDate(d);
        let dateItems = cache[dk] || [];

        // 削除前に既存の first_seen を控えておき、再検索で NEW バッジが
        // リセットされないようにする(同一 URL は初回発見時刻を維持)
        const prevSeen = {};
        dateItems.forEach(item => {
            if (item.first_seen) prevSeen[item.url] = item.first_seen;
        });

        if (checkedSet) {
            dateItems = dateItems.filter(item => !checkedSet.has(item.company_name));
        }

        const newDateItems = byDate[dk] || [];
        newDateItems.forEach(item => {
            if (!dateItems.some(saved => saved.url === item.url)) {
                // このブラウザで初めて見つけた時刻を記録(「NEW」バッジ表示に使う)
                dateItems.push({ ...item, first_seen: prevSeen[item.url] || Date.now() });
            }
        });

        cache[dk] = dateItems;
    }

    localStorage.setItem(STORAGE_KEY, JSON.stringify(cache));
    renderFromCacheRange();
}

function getDateRange() {
    const startDate = document.getElementById('startDateInput').value;
    const endDate = document.getElementById('endDateInput').value;
    return { startDate, endDate };
}

function collectItemsInRange(startDate, endDate) {
    const cache = getCache();
    let allItems = [];
    const s = parseDate(startDate);
    const e = parseDate(endDate);
    for (let d = new Date(s); d <= e; d.setDate(d.getDate() + 1)) {
        const dk = formatDate(d);
        const dateItems = cache[dk] || [];
        allItems = allItems.concat(dateItems);
    }
    // Deduplicate by URL
    const seen = new Set();
    allItems = allItems.filter(item => {
        if (seen.has(item.url)) return false;
        seen.add(item.url);
        return true;
    });
    allItems.sort((a, b) => new Date(b.date) - new Date(a.date));
    return allItems;
}

function renderFromCacheRange() {
    const { startDate, endDate } = getDateRange();
    const kw = document.getElementById('keywordInput').value;
    if (kw) {
        filterNews('search', kw);
    } else {
        const items = collectItemsInRange(startDate, endDate);
        renderGrid(items, startDate, endDate);
    }
}

function deleteItem(dateKey, url) {
    let cache = getCache();
    if (cache[dateKey]) {
        cache[dateKey] = cache[dateKey].filter(item => item.url !== url);
        localStorage.setItem(STORAGE_KEY, JSON.stringify(cache));
        renderFromCacheRange();
    }
}

const TOPIC_KEYWORDS = {
    'product': ['商品', '発売', 'キャンペーン', 'コラボ', '限定', 'フェア', 'プレゼント', 'セール', 'アイス', '弁当', 'スイーツ', 'グッズ', '予約', 'メニュー'],
    'csr': ['環境', 'サステナ', 'エコ', 'CO2', '寄贈', '募金', '支援', 'フードバンク', 'リサイクル', '脱炭素', '賞'],
    'corporate': ['人事', '組織', '決算', '社長', '役員', '提携', '買収', '方針', '報告', 'IR', '株式'],
    'store': ['店舗', '店', 'オープン', '改装', '地域', '地産', '県', '市', '都', '府', '建築', '開発'],
    'dx': ['アプリ', 'DX', 'システム', 'デジタル', '決済', 'AI', 'ロボット']
};

// 画面のフィルタボタンと同じ分類の表示名(CSV の「分類」列で使う)
const TOPIC_LABELS = {
    'product': '商品・販促',
    'csr': '環境・社会',
    'corporate': '経営・人事',
    'store': '店舗・地域',
    'dx': 'DX・デジタル',
};

// タイトルをキーワード分類する。複数該当は「・」区切り、該当なしは「その他」
function classifyTopics(title) {
    const hits = Object.keys(TOPIC_KEYWORDS)
        .filter(key => TOPIC_KEYWORDS[key].some(kw => String(title || '').includes(kw)))
        .map(key => TOPIC_LABELS[key]);
    return hits.length ? hits.join('・') : 'その他';
}

let currentFilterMode = 'category';
let currentCategory = 'all';
let currentSearchText = '';
let currentSort = 'new';
let dashboardMonth = '';

function setSort(value) {
    currentSort = value;
    // 現在の表示モードを維持したまま並び替えて再描画
    if (currentFilterMode === 'search') {
        filterNews('search', currentSearchText);
    } else if (currentFilterMode === 'bookmarks' || currentFilterMode === 'unread') {
        filterNews(currentFilterMode, '');
    } else {
        filterNews('category', currentCategory);
    }
}

function filterNews(mode, value) {
    currentFilterMode = mode;
    const { startDate, endDate } = getDateRange();
    let itemsToDisplay = [];
    const cache = getCache();

    if (mode === 'search') {
        currentSearchText = value;
        if (currentSearchText) {
            // Search across all cached data
            Object.keys(cache).forEach(key => {
                itemsToDisplay = itemsToDisplay.concat(cache[key]);
            });
            const seen = new Set();
            itemsToDisplay = itemsToDisplay.filter(item => {
                if (seen.has(item.url)) return false;
                seen.add(item.url);
                return true;
            });
            document.querySelectorAll('.filter-btn').forEach(btn => btn.classList.remove('active'));
        } else {
            itemsToDisplay = collectItemsInRange(startDate, endDate);
        }
    } else if (mode === 'category') {
        currentCategory = value;
        currentSearchText = '';
        document.getElementById('keywordInput').value = '';
        document.querySelectorAll('.filter-btn').forEach(btn => btn.classList.remove('active'));
        document.getElementById('btn-' + value).classList.add('active');
        itemsToDisplay = collectItemsInRange(startDate, endDate);
    } else if (mode === 'unread') {
        currentSearchText = '';
        document.getElementById('keywordInput').value = '';
        document.querySelectorAll('.filter-btn').forEach(btn => btn.classList.remove('active'));
        document.getElementById('btn-unread').classList.add('active');
        itemsToDisplay = collectItemsInRange(startDate, endDate);
    } else if (mode === 'bookmarks') {
        currentSearchText = '';
        document.getElementById('keywordInput').value = '';
        document.querySelectorAll('.filter-btn').forEach(btn => btn.classList.remove('active'));
        document.getElementById('btn-bookmarks').classList.add('active');
        itemsToDisplay = Object.values(getBookmarks());
    }
    renderGrid(itemsToDisplay, startDate, endDate);
}

function checkFilter(item, readSet) {
    if (currentFilterMode === 'bookmarks') {
        return true;
    }
    if (currentFilterMode === 'unread') {
        return !(readSet || getReadSet())[item.url];
    }
    if (currentFilterMode === 'search') {
        if (!currentSearchText) return true;
        return item.title.toLowerCase().includes(currentSearchText.toLowerCase());
    } else {
        if (currentCategory === 'all') return true;
        const keywords = TOPIC_KEYWORDS[currentCategory] || [];
        return keywords.some(kw => item.title.includes(kw));
    }
}

function sortItems(items) {
    const sorted = items.slice();
    if (currentSort === 'old') {
        sorted.sort((a, b) => new Date(a.date) - new Date(b.date));
    } else if (currentSort === 'company') {
        sorted.sort((a, b) =>
            (a.company_name || '').localeCompare(b.company_name || '', 'ja') ||
            (new Date(b.date) - new Date(a.date)));
    } else {
        sorted.sort((a, b) => new Date(b.date) - new Date(a.date));
    }
    return sorted;
}

// 表示中の並び順に応じたグループ見出しラベル(日付順なら日付、企業別なら企業名)
function groupLabel(item, todayStr, yesterdayStr) {
    if (currentSort === 'company') return item.company_name || '';
    if (item.date === todayStr) return '今日 ・ ' + item.date;
    if (item.date === yesterdayStr) return '昨日 ・ ' + item.date;
    return item.date;
}

function highlightText(text, keyword) {
    if (!keyword) return text;
    // 正規表現のメタ文字をエスケープ(「(」などの入力でエラーにならないように)
    const escaped = keyword.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
    const regex = new RegExp(`(${esc(escaped)})`, 'gi');
    return text.replace(regex, '<mark>$1</mark>');
}

function renderGrid(items, startDate, endDate) {
    const gridContainer = document.getElementById('result-grid');
    const linkContainer = document.getElementById('link-only-container');
    const countBadge = document.getElementById('result-count');
    const emptyMsg = document.getElementById('empty-message');
    const dateDisplay = document.getElementById('display-date-str');

    lastRenderedSource = items;

    if (dateDisplay) {
        if (currentFilterMode === 'bookmarks') {
            dateDisplay.textContent = 'Bookmarks: 保存したニュース';
        } else if (currentFilterMode === 'search' && currentSearchText) {
            dateDisplay.textContent = 'Search: all cached data';
        } else if (startDate === endDate) {
            dateDisplay.textContent = 'Target: ' + startDate;
        } else {
            dateDisplay.textContent = 'Range: ' + startDate + ' ~ ' + (endDate || startDate);
        }
    }

    const bookmarks = getBookmarks();
    const readSet = getReadSet();

    const filteredItems = sortItems(items.filter(item => checkFilter(item, readSet)));
    lastRenderedItems = filteredItems;

    if (!filteredItems || filteredItems.length === 0) {
        gridContainer.innerHTML = '';
        linkContainer.innerHTML = '';
        linkContainer.classList.add('hidden');
        if (emptyMsg) {
            emptyMsg.classList.remove('hidden');
            const isFiltering = (currentFilterMode === 'search' && currentSearchText) ||
                (currentFilterMode === 'category' && currentCategory !== 'all') ||
                currentFilterMode === 'unread';
            const msgText = (items.length > 0 && isFiltering) ? "条件に一致するニュースはありません" : "まだデータがありません";
            emptyMsg.querySelector('p.text-xl').textContent = msgText;
        }
        if (countBadge) countBadge.textContent = '0 items';
        return;
    }

    if (emptyMsg) emptyMsg.classList.add('hidden');
    if (countBadge) {
        // 絞り込みで隠れている件数が分かるよう「表示中 / 全体」で示す
        countBadge.textContent = filteredItems.length === items.length
            ? filteredItems.length + ' items'
            : filteredItems.length + ' / ' + items.length + ' items';
    }

    const linkOnlyItems = filteredItems.filter(i => i.is_link_only);
    const cardItems = filteredItems.filter(i => !i.is_link_only);

    const now = new Date();
    const todayStr = formatDate(now);
    const yesterday = new Date(now);
    yesterday.setDate(yesterday.getDate() - 1);
    const yesterdayStr = formatDate(yesterday);
    let prevGroup = null;

    gridContainer.innerHTML = cardItems.map(item => {
        // 日付順(または企業別)のグループ見出しを差し込む
        let header = '';
        const label = groupLabel(item, todayStr, yesterdayStr);
        if (label !== prevGroup) {
            prevGroup = label;
            const icon = currentSort === 'company' ? 'fa-building' : 'far fa-calendar-alt';
            header = `
            <div class="col-span-full flex items-center gap-3 mt-2 -mb-2 first:mt-0">
                <span class="text-sm font-black text-slate-500 whitespace-nowrap"><i class="fas ${icon} mr-2 text-slate-300"></i>${esc(label)}</span>
                <span class="flex-1 border-t border-slate-200"></span>
            </div>`;
        }
        const bookmarked = !!bookmarks[item.url];
        const isRead = !!readSet[item.url];
        const isNew = !isRead && item.first_seen && (Date.now() - item.first_seen) < NEW_BADGE_MS;
        let bgClass = "bg-white";
        let textClass = "text-slate-800";
        if (item.is_error) {
            bgClass = "bg-red-50/80";
            textClass = "text-red-700 font-bold";
        }
        if (item.title && item.title.includes("【") && !item.is_error) {
            bgClass = "bg-red-50/80";
            textClass = "text-red-700 font-bold";
        }

        let displayTitle = esc(item.title);
        if (currentFilterMode === 'search' && currentSearchText) {
            displayTitle = highlightText(displayTitle, currentSearchText);
        }
        return header + `
        <div class="relative ${bgClass} ${isRead ? 'opacity-55' : ''} p-6 rounded-xl shadow-md border-t-4 hover:-translate-y-1 hover:shadow-lg transition-all duration-200 ease-out group flex flex-col h-full news-card" style="border-color: ${esc(item.badge_color)}">
            <div class="flex items-center justify-between mb-4">
                <div class="flex items-center min-w-0">
                    <img src="https://www.google.com/s2/favicons?domain=${esc(item.url)}&sz=32" alt="ロゴ" class="w-5 h-5 mr-3 rounded-full shadow-sm bg-white p-0.5 opacity-80">
                    <span class="text-xs font-bold text-slate-500 uppercase tracking-wider truncate">${esc(item.company_name)}</span>
                    ${isNew ? '<span class="ml-2 px-1.5 py-0.5 bg-rose-100 text-rose-600 rounded font-black text-[10px] tracking-wider flex-shrink-0" title="このブラウザで24時間以内に初めて取得">NEW</span>' : ''}
                </div>
                <span class="text-xs font-medium text-slate-400 bg-slate-100 px-2 py-1 rounded-full whitespace-nowrap ml-2"><i class="far fa-calendar-alt mr-1"></i>${esc(item.date)}</span>
            </div>
            <a href="${esc(item.url)}" target="_blank" onclick="markRead(this, decodeURIComponent('${encodeURIComponent(item.url)}'))" class="block flex-1 flex flex-col group-hover:opacity-100">
                <h3 class="text-lg font-bold ${textClass} leading-snug group-hover:text-blue-600 transition-colors flex-grow">
                    ${displayTitle}
                </h3>
                <div class="mt-5 flex items-center text-sm text-blue-600 font-bold opacity-0 -translate-x-2 group-hover:opacity-100 group-hover:translate-x-0 transition-all duration-300">
                    <span>Read Article</span><i class="fas fa-arrow-right ml-2"></i>
                </div>
            </a>
            <button onclick="toggleBookmark(decodeURIComponent('${encodeURIComponent(item.url)}'))" class="absolute top-2 right-9 ${bookmarked ? 'text-amber-400 opacity-100' : 'text-slate-200 opacity-0 group-hover:opacity-100'} hover:text-amber-500 transition-opacity p-1 bookmark-btn" title="${bookmarked ? 'ブックマーク解除' : 'ブックマーク'}"><i class="fas fa-star"></i></button>
            <button onclick="deleteItem('${esc(item.date)}', decodeURIComponent('${encodeURIComponent(item.url)}'))" class="absolute top-2 right-2 text-slate-200 hover:text-red-400 opacity-0 group-hover:opacity-100 transition-opacity p-1" title="削除"><i class="fas fa-times-circle"></i></button>
        </div>`;
    }).join('');

    if (linkOnlyItems.length > 0) {
        linkContainer.classList.remove('hidden');
        linkContainer.innerHTML = `
            <h3 class="col-span-full text-sm font-bold text-slate-500 mb-2 mt-8">
                ※直接確認できなかったサイト（公式サイトへ移動）
            </h3>
        ` + linkOnlyItems.map(item => `
            <a href="${esc(item.url)}" target="_blank" class="flex items-center justify-between p-3 bg-blue-50 border border-blue-200 rounded-lg hover:bg-blue-100 transition-colors group shadow-sm">
                <div class="flex items-center overflow-hidden">
                    <span class="w-2.5 h-2.5 rounded-full bg-blue-500 mr-3 flex-shrink-0"></span>
                    <span class="font-bold text-blue-700 text-sm mr-3 whitespace-nowrap">${esc(item.company_name)}</span>
                    <span class="text-sm text-slate-600 truncate group-hover:text-blue-800">${esc(item.title)}</span>
                </div>
                <div class="flex items-center flex-shrink-0 ml-2">
                    <span class="text-xs text-slate-400 mr-2">${esc(item.date)}</span>
                    <i class="fas fa-external-link-alt text-blue-400 group-hover:text-blue-600"></i>
                </div>
            </a>
        `).join('');
    } else {
        linkContainer.classList.add('hidden');
        linkContainer.innerHTML = '';
    }
}

// ===== AI アシスタント(ダイジェスト+質問) =====
let digestLoadedOnce = false;

function toggleAiDigest() {
    const modal = document.getElementById('digest-modal');
    if (!modal) return;
    if (modal.classList.contains('hidden')) {
        modal.classList.remove('hidden');
        modal.classList.add('flex');
        // 初回表示のみ自動生成(タブを切り替えて戻っても再生成しない)
        if (!digestLoadedOnce) {
            digestLoadedOnce = true;
            loadAiDigest();
        }
    } else {
        modal.classList.add('hidden');
        modal.classList.remove('flex');
    }
}

function switchAiTab(tab) {
    const digestPane = document.getElementById('digest-pane');
    const askPane = document.getElementById('ask-pane');
    const isAsk = tab === 'ask';
    digestPane.classList.toggle('hidden', isAsk);
    digestPane.classList.toggle('flex', !isAsk);
    askPane.classList.toggle('hidden', !isAsk);
    askPane.classList.toggle('flex', isAsk);
    document.getElementById('tab-digest').classList.toggle('active', !isAsk);
    document.getElementById('tab-ask').classList.toggle('active', isAsk);
    if (isAsk) document.getElementById('ask-input').focus();
}

// 選択中の期間・企業をクエリ条件として集める(/digest・/ask 共通)
function currentAiScope() {
    const { startDate, endDate } = getDateRange();
    const companies = [];
    document.querySelectorAll('input[name="companies"]:checked').forEach(cb => {
        companies.push(cb.value);
    });
    return { startDate, endDate, companies };
}

function copyToClipboard(text, btn) {
    if (!text) return;
    const done = () => {
        if (!btn) return;
        const original = btn.innerHTML;
        btn.innerHTML = '<i class="fas fa-check mr-1"></i>コピーしました';
        setTimeout(() => { btn.innerHTML = original; }, 1500);
    };
    if (navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(text).then(done).catch(() => {});
    } else {
        // 非 HTTPS 環境向けフォールバック
        const ta = document.createElement('textarea');
        ta.value = text;
        document.body.appendChild(ta);
        ta.select();
        document.execCommand('copy');
        document.body.removeChild(ta);
        done();
    }
}

function copyDigest(btn) {
    copyToClipboard(document.getElementById('digest-content').textContent, btn);
}

function askAi() {
    const input = document.getElementById('ask-input');
    const sendBtn = document.getElementById('ask-send');
    const log = document.getElementById('ask-log');
    const question = input.value.trim();
    if (!question || sendBtn.disabled) return;

    const empty = document.getElementById('ask-empty');
    if (empty) empty.remove();

    input.value = '';
    sendBtn.disabled = true;

    const { startDate, endDate, companies } = currentAiScope();

    // 質問バブル+回答プレースホルダを追加
    const entry = document.createElement('div');
    entry.innerHTML = `
        <div class="flex justify-end mb-2"><div class="max-w-[85%] px-4 py-2.5 bg-blue-600 text-white text-sm rounded-2xl rounded-br-sm whitespace-pre-wrap">${esc(question)}</div></div>
        <div class="flex"><div class="ask-answer max-w-[85%] px-4 py-2.5 bg-slate-100 text-slate-700 text-sm rounded-2xl rounded-bl-sm whitespace-pre-wrap leading-relaxed"><i class="fas fa-circle-notch fa-spin mr-2 text-slate-400"></i>考えています...</div></div>`;
    log.appendChild(entry);
    log.scrollTop = log.scrollHeight;

    const answerEl = entry.querySelector('.ask-answer');
    const finish = (text, isError) => {
        answerEl.textContent = text;
        if (isError) {
            answerEl.classList.remove('bg-slate-100', 'text-slate-700');
            answerEl.classList.add('bg-red-50', 'text-red-700', 'border', 'border-red-200');
        }
        sendBtn.disabled = false;
        log.scrollTop = log.scrollHeight;
    };

    fetch('/ask', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ question, start_date: startDate, end_date: endDate, companies }),
    })
        .then(r => r.json().then(data => ({ ok: r.ok, data })))
        .then(({ ok, data }) => {
            if (data.error || !ok) {
                finish(data.error || '回答の取得に失敗しました。', true);
            } else if (!data.answer) {
                finish(data.message || 'この期間の収集済みニュースがありません。', true);
            } else {
                finish(data.answer, false);
            }
        })
        .catch(() => finish('サーバーとの通信に失敗しました。', true));
}

function loadAiDigest() {
    const loading = document.getElementById('digest-loading');
    const errorEl = document.getElementById('digest-error');
    const content = document.getElementById('digest-content');
    const meta = document.getElementById('digest-meta');
    loading.classList.remove('hidden');
    errorEl.classList.add('hidden');
    content.classList.add('hidden');

    const { startDate, endDate } = getDateRange();
    const params = new URLSearchParams();
    if (startDate) params.append('start_date', startDate);
    if (endDate) params.append('end_date', endDate);
    document.querySelectorAll('input[name="companies"]:checked').forEach(cb => {
        params.append('companies', cb.value);
    });

    fetch('/digest?' + params.toString())
        .then(r => r.json().then(data => ({ ok: r.ok, data })))
        .then(({ ok, data }) => {
            loading.classList.add('hidden');
            if (data.error || !ok) {
                errorEl.textContent = data.error || 'ダイジェストの取得に失敗しました。';
                errorEl.classList.remove('hidden');
                return;
            }
            if (!data.digest) {
                errorEl.textContent = data.message || 'この期間の収集済みニュースがありません。';
                errorEl.classList.remove('hidden');
                return;
            }
            content.textContent = data.digest;
            content.classList.remove('hidden');
            meta.textContent = `対象: ${startDate} 〜 ${endDate} ・ ${data.item_count}件のニュース` + (data.cached ? ' ・ キャッシュ' : '');
        })
        .catch(() => {
            loading.classList.add('hidden');
            errorEl.textContent = 'サーバーとの通信に失敗しました。';
            errorEl.classList.remove('hidden');
        });
}

function toggleSummary() {
    const modal = document.getElementById('summary-modal');
    if (modal.classList.contains('hidden')) {
        const now = new Date();
        dashboardMonth = now.getFullYear() + '-' + String(now.getMonth() + 1).padStart(2, '0');
        calculateSummary(dashboardMonth);
        showSummaryView();
        modal.classList.remove('hidden');
        modal.classList.add('flex');
    } else {
        modal.classList.add('hidden');
        modal.classList.remove('flex');
    }
}

function calculateSummary(monthPrefix) {
    if (monthPrefix) dashboardMonth = monthPrefix;
    const cache = getCache();

    const companyData = {};
    let totalItems = 0;

    Object.keys(cache).forEach(dateKey => {
        if (dateKey.startsWith(dashboardMonth)) {
            cache[dateKey].forEach(item => {
                if (item.is_link_only || item.is_error) return;
                const name = item.company_name;
                if (!companyData[name]) {
                    companyData[name] = { count: 0, dates: new Set(), badgeColor: item.badge_color };
                }
                companyData[name].count++;
                companyData[name].dates.add(item.date);
                totalItems++;
            });
        }
    });

    const sorted = Object.entries(companyData).sort((a, b) => b[1].count - a[1].count);
    const list = document.getElementById('summary-list');
    const totalEl = document.getElementById('summary-total');
    const monthEl = document.getElementById('summary-month');

    monthEl.textContent = dashboardMonth;
    totalEl.textContent = totalItems;

    if (sorted.length === 0) {
        list.innerHTML = '<div class="text-center text-slate-400 py-10"><i class="fas fa-inbox text-3xl mb-3 block opacity-30"></i>この月のデータはありません</div>';
        return;
    }

    const maxCount = sorted[0][1].count;

    list.innerHTML = sorted.map(([name, data], index) => {
        const percent = (data.count / maxCount) * 100;
        const dateList = Array.from(data.dates)
            .map(d => parseInt(d.split('-')[2]))
            .sort((a, b) => a - b)
            .map(d => String(d).padStart(2, '0'))
            .join(', ');

        const badgeColor = data.badgeColor || "#cbd5e1";

        return `
        <div class="mb-3 cursor-pointer hover:bg-blue-50 rounded-xl p-3 -mx-3 transition-all group border border-transparent hover:border-blue-200 hover:shadow-sm" onclick="showCompanyDetail(decodeURIComponent('${encodeURIComponent(name)}'), '${esc(badgeColor)}')">
            <div class="flex justify-between text-sm font-bold text-slate-700 mb-1">
                <span class="flex items-center">
                    <span class="w-3 h-3 rounded-full mr-2" style="background-color: ${esc(badgeColor)}"></span>
                    ${index + 1}. ${esc(name)}
                </span>
                <span class="flex items-center text-blue-500">
                    ${data.count}件
                    <i class="fas fa-chevron-right ml-2 text-sm"></i>
                </span>
            </div>
            <div class="w-full bg-slate-100 rounded-full h-2.5 mb-1">
                <div class="bg-blue-500 h-2.5 rounded-full transition-all duration-500" style="width: ${percent}%"></div>
            </div>
            <div class="text-[10px] text-slate-400 font-mono pl-5">
                <i class="far fa-clock mr-1"></i>Updates: ${dateList}
            </div>
        </div>
        `;
    }).join('');
}

function shiftDashboardMonth(amount) {
    const parts = dashboardMonth.split('-');
    const d = new Date(parseInt(parts[0]), parseInt(parts[1]) - 1 + amount, 1);
    dashboardMonth = d.getFullYear() + '-' + String(d.getMonth() + 1).padStart(2, '0');
    calculateSummary(dashboardMonth);
    showSummaryView();
}

function showSummaryView() {
    document.getElementById('dashboard-summary-view').classList.remove('hidden');
    document.getElementById('dashboard-detail-view').classList.add('hidden');
}

function showCompanyDetail(companyName, badgeColor) {
    const cache = getCache();
    const items = [];
    Object.keys(cache).forEach(dateKey => {
        if (dateKey.startsWith(dashboardMonth)) {
            cache[dateKey].forEach(item => {
                if (item.company_name === companyName && !item.is_link_only && !item.is_error) {
                    items.push(item);
                }
            });
        }
    });
    items.sort((a, b) => new Date(a.date) - new Date(b.date));

    document.getElementById('detail-company-name').textContent = companyName;
    document.getElementById('detail-company-badge').style.backgroundColor = badgeColor;
    document.getElementById('detail-month-display').textContent = dashboardMonth;
    document.getElementById('detail-count').textContent = items.length + '件';

    const list = document.getElementById('detail-news-list');
    if (items.length === 0) {
        list.innerHTML = '<div class="text-center text-slate-400 py-10"><i class="fas fa-inbox text-3xl mb-3 block opacity-30"></i>この月のニュースはありません</div>';
    } else {
        list.innerHTML = items.map(item => {
            return `
            <a href="${esc(item.url)}" target="_blank" class="block p-4 bg-white border border-slate-200 rounded-xl hover:border-blue-300 hover:shadow-md transition-all group">
                <div class="flex items-center justify-between mb-2">
                    <span class="text-xs font-bold text-slate-400 bg-slate-100 px-2.5 py-1 rounded-full">
                        <i class="far fa-calendar-alt mr-1"></i>${esc(item.date)}
                    </span>
                    <i class="fas fa-external-link-alt text-slate-300 group-hover:text-blue-500 transition-colors"></i>
                </div>
                <h4 class="text-sm font-bold text-slate-700 group-hover:text-blue-600 transition-colors leading-relaxed">
                    ${esc(item.title)}
                </h4>
            </a>`;
        }).join('');
    }

    document.getElementById('dashboard-summary-view').classList.add('hidden');
    document.getElementById('dashboard-detail-view').classList.remove('hidden');
}
