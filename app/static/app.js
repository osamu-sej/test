function toggleCategory(source, cls) {
    document.querySelectorAll('.' + cls).forEach(el => el.checked = source.checked);
}

const STORAGE_KEY = 'retail_news_date_cache_v1';

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

    startInput.addEventListener('change', function() { renderFromCacheRange(); });
    endInput.addEventListener('change', function() { renderFromCacheRange(); });

    searchInput.addEventListener('input', function(e) {
        const keyword = e.target.value;
        filterNews('search', keyword);
    });
});

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

        if (checkedSet) {
            dateItems = dateItems.filter(item => !checkedSet.has(item.company_name));
        }

        const newDateItems = byDate[dk] || [];
        newDateItems.forEach(item => {
            if (!dateItems.some(saved => saved.url === item.url)) {
                dateItems.push(item);
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

let currentFilterMode = 'category';
let currentCategory = 'all';
let currentSearchText = '';
let dashboardMonth = '';

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
            itemsToDisplay.sort((a, b) => new Date(b.date) - new Date(a.date));
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
    }
    renderGrid(itemsToDisplay, startDate, endDate);
}

function checkFilter(title) {
    if (currentFilterMode === 'search') {
        if (!currentSearchText) return true;
        return title.toLowerCase().includes(currentSearchText.toLowerCase());
    } else {
        if (currentCategory === 'all') return true;
        const keywords = TOPIC_KEYWORDS[currentCategory] || [];
        return keywords.some(kw => title.includes(kw));
    }
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

    if (dateDisplay) {
        if (currentFilterMode === 'search' && currentSearchText) {
            dateDisplay.textContent = 'Search: all cached data';
        } else if (startDate === endDate) {
            dateDisplay.textContent = 'Target: ' + startDate;
        } else {
            dateDisplay.textContent = 'Range: ' + startDate + ' ~ ' + (endDate || startDate);
        }
    }

    const filteredItems = items.filter(item => checkFilter(item.title));

    if (!filteredItems || filteredItems.length === 0) {
        gridContainer.innerHTML = '';
        linkContainer.innerHTML = '';
        if (emptyMsg) {
            emptyMsg.classList.remove('hidden');
            const isFiltering = (currentFilterMode === 'search' && currentSearchText) || (currentFilterMode === 'category' && currentCategory !== 'all');
            const msgText = (items.length > 0 && isFiltering) ? "条件に一致するニュースはありません" : "まだデータがありません";
            emptyMsg.querySelector('p.text-xl').textContent = msgText;
        }
        if (countBadge) countBadge.textContent = '0 items';
        return;
    }

    if (emptyMsg) emptyMsg.classList.add('hidden');
    if (countBadge) countBadge.textContent = filteredItems.length + ' items';

    const linkOnlyItems = filteredItems.filter(i => i.is_link_only);
    const cardItems = filteredItems.filter(i => !i.is_link_only);

    gridContainer.innerHTML = cardItems.map(item => {
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
        return `
        <div class="relative ${bgClass} p-6 rounded-xl shadow-md border-t-4 hover:-translate-y-1 hover:shadow-lg transition-all duration-200 ease-out group flex flex-col h-full news-card" style="border-color: ${esc(item.badge_color)}">
            <div class="flex items-center justify-between mb-4">
                <div class="flex items-center">
                    <img src="https://www.google.com/s2/favicons?domain=${esc(item.url)}&sz=32" alt="ロゴ" class="w-5 h-5 mr-3 rounded-full shadow-sm bg-white p-0.5 opacity-80">
                    <span class="text-xs font-bold text-slate-500 uppercase tracking-wider">${esc(item.company_name)}</span>
                </div>
                <span class="text-xs font-medium text-slate-400 bg-slate-100 px-2 py-1 rounded-full whitespace-nowrap"><i class="far fa-calendar-alt mr-1"></i>${esc(item.date)}</span>
            </div>
            <a href="${esc(item.url)}" target="_blank" class="block flex-1 flex flex-col group-hover:opacity-100">
                <h3 class="text-lg font-bold ${textClass} leading-snug group-hover:text-blue-600 transition-colors flex-grow">
                    ${displayTitle}
                </h3>
                <div class="mt-5 flex items-center text-sm text-blue-600 font-bold opacity-0 -translate-x-2 group-hover:opacity-100 group-hover:translate-x-0 transition-all duration-300">
                    <span>Read Article</span><i class="fas fa-arrow-right ml-2"></i>
                </div>
            </a>
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
