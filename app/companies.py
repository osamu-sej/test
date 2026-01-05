COMPANIES = [
    # --- コンビニエンスストア ---
    {
        "id": "seven_2026", "name": "セブン&アイ・HD(2026)", "category": "コンビニ",
        "url": "https://www.7andi.com/company/news/index.html", 
        "scraper_type": "auto",
        "badge_color": "#EA5514",
        "date_format": "%Y年%m月%d日"
    },
    {
        "id": "seven_2025", "name": "セブン&アイ・HD(2025)", "category": "コンビニ",
        "url": "https://www.7andi.com/company/news/2025.html",
        "scraper_type": "auto",
        "badge_color": "#EA5514",
        "date_format": "%Y年%m月%d日"
    },
    # 【修正】URLを 2026.html に戻しました（現在は404でもOK）
    {
        "id": "seven_sej_2026", "name": "セブン-イレブン(2026)", "category": "コンビニ",
        "url": "https://www.sej.co.jp/company/news_release/news/2026.html",
        "scraper_type": "auto",
        "badge_color": "#EA5514",
        "date_format": "%Y.%m.%d"
    },
    {
        "id": "seven_sej_2025", "name": "セブン-イレブン(2025)", "category": "コンビニ",
        "url": "https://www.sej.co.jp/company/news_release/news/2025.html",
        "scraper_type": "auto",
        "badge_color": "#EA5514",
        "date_format": "%Y.%m.%d"
    },
    {
        "id": "famima", "name": "ファミリーマート", "category": "コンビニ",
        "url": "https://www.family.co.jp/company/news_releases.html",
        "scraper_type": "auto",
        "badge_color": "#00A0E9",
        "date_format": "%Y年%m月%d日"
    },
    {
        "id": "ministop", "name": "ミニストップ", "category": "コンビニ",
        "url": "https://www.ministop.co.jp/corporate/release/",
        "scraper_type": "auto",
        "badge_color": "#FFD200",
        "date_format": "%Y.%m.%d"
    },
    {
        "id": "lawson", "name": "ローソン", "category": "コンビニ",
        "url": "https://www.lawson.co.jp/company/news/",
        "scraper_type": "auto",
        "badge_color": "#0068B7",
        "date_format": "%Y.%m.%d"
    },

    # --- スーパー ---
    {
        "id": "aeon", "name": "イオン", "category": "スーパー",
        "url": "https://www.aeon.info/news/",
        "scraper_type": "auto",
        "badge_color": "#AE0E36",
        "date_format": "%Y.%m.%d"
    },
    {
        "id": "itoyokado", "name": "イトーヨーカドー", "category": "スーパー",
        "url": "https://www.itoyokado.co.jp/company/newsrelease.html",
        "scraper_type": "auto",
        "badge_color": "#D70035",
        "date_format": "%Y.%m.%d"
    },
    {
        "id": "life", "name": "ライフ", "category": "スーパー",
        "url": "https://www.lifecorp.jp/company/info/news/",
        "scraper_type": "auto",
        "badge_color": "#F7931E",
        "date_format": "%Y.%m.%d"
    },
    {
        "id": "seiyu", "name": "西友", "category": "スーパー",
        "url": "https://www.seiyu.co.jp/company/pressrelease/",
        "scraper_type": "auto",
        "badge_color": "#E60012",
        "date_format": "%Y年%m月%d日"
    },
    {
        "id": "yaoko", "name": "ヤオコー", "category": "スーパー",
        "url": "https://www.yaoko-net.com/news/",
        "scraper_type": "auto",
        "badge_color": "#800080",
        "date_format": "%Y.%m.%d"
    },

    # --- ドラッグストア ---
    {
        "id": "welcia", "name": "ウエルシアHD", "category": "ドラッグストア",
        "url": "https://www.welcia.co.jp/ja/news.html",
        "scraper_type": "auto",
        "badge_color": "#005BAC",
        "date_format": "%Y.%m.%d"
    },
    {
        "id": "tsuruha", "name": "ツルハドラッグ", "category": "ドラッグストア",
        "url": "https://www.tsuruha.co.jp/news/news/",
        "scraper_type": "auto",
        "badge_color": "#E60012",
        "date_format": "%Y年%m月%d日"
    },
    {
        "id": "matsukiyo", "name": "マツキヨココカラ", "category": "ドラッグストア",
        "url": "https://www.matsukiyococokara.com/news/",
        "scraper_type": "auto",
        "badge_color": "#FCE300",
        "date_format": "%Y.%m.%d"
    },
    {
        "id": "sugi", "name": "スギ薬局(HD)", "category": "ドラッグストア",
        "url": "https://www.sugi-hd.co.jp/news/",
        "scraper_type": "force_link",
        "badge_color": "#E60012",
        "date_format": "%Y.%m.%d"
    },

    # --- ディスカウント ---
    {
        "id": "donki", "name": "ドン・キホーテ", "category": "ディスカウント",
        "url": "https://ppih.co.jp/news/",
        "scraper_type": "auto",
        "badge_color": "#000000",
        "date_format": "%Y.%m.%d"
    },
    {
        "id": "gyomu", "name": "業務スーパー", "category": "ディスカウント",
        "url": "https://www.gyomusuper.jp/topics/",
        "scraper_type": "auto",
        "badge_color": "#228B22",
        "date_format": "%Y.%m.%d"
    },
    {
        "id": "trial", "name": "トライアルHD", "category": "ディスカウント",
        "url": "https://trial-holdings.inc/news/",
        "scraper_type": "auto",
        "badge_color": "#000080",
        "date_format": "%Y.%m.%d"
    },
    {
        "id": "dairiki", "name": "大黒天物産", "category": "ディスカウント",
        "url": "https://www.e-dkt.co.jp/ir/",
        "scraper_type": "auto",
        "badge_color": "#FF00FF",
        "date_format": "%Y.%m.%d"
    },

    # --- 飲料メーカー ---
    {
        "id": "suntory", "name": "サントリー食品", "category": "飲料",
        "url": "https://www.suntory.co.jp/softdrink/news/",
        "scraper_type": "auto",
        "badge_color": "#00AEEF",
        "date_format": "%Y年%m月%d日"
    },
    {
        "id": "cocacola", "name": "コカ・コーラBJI", "category": "飲料",
        "url": "https://www.ccbji.co.jp/news/",
        "scraper_type": "auto",
        "badge_color": "#F40009",
        "date_format": "%Y年%m月%d日"
    },
    {
        "id": "kirin", "name": "キリンHD", "category": "飲料",
        "url": "https://www.kirinholdings.com/jp/newsroom/release/",
        "scraper_type": "force_link",
        "badge_color": "#D9000D",
        "date_format": "%Y年%m月%d日"
    },
    {
        "id": "asahi_inryo", "name": "アサヒ飲料", "category": "飲料",
        "url": "https://www.asahiinryo.co.jp/company/newsrelease/",
        "scraper_type": "auto",
        "badge_color": "#004899",
        "date_format": "%Y.%m.%d"
    },
    {
        "id": "itoen", "name": "伊藤園", "category": "飲料",
        "url": "https://www.itoen.co.jp/news/release/",
        "scraper_type": "auto",
        "badge_color": "#007B43",
        "date_format": "%Y.%m.%d"
    },

    # --- お菓子メーカー ---
    {
        "id": "meiji", "name": "明治", "category": "お菓子",
        "url": "https://www.meiji.co.jp/corporate/pressrelease/",
        "scraper_type": "auto",
        "badge_color": "#ED1A3D",
        "date_format": "%Y/%m/%d"
    },
    {
        "id": "calbee", "name": "カルビー", "category": "お菓子",
        "url": "https://www.calbee.co.jp/news/",
        "scraper_type": "auto",
        "badge_color": "#DA291C",
        "date_format": "%Y年%m月%d日"
    },
    {
        "id": "lotte_2026", "name": "ロッテ(2026)", "category": "お菓子",
        "url": "https://www.lotte.co.jp/info/news/2026.html",
        "scraper_type": "auto",
        "badge_color": "#D70035",
        "date_format": "%Y.%m.%d"
    },
    {
        "id": "lotte_2025", "name": "ロッテ(2025)", "category": "お菓子",
        "url": "https://www.lotte.co.jp/info/news/2025.html",
        "scraper_type": "auto",
        "badge_color": "#D70035",
        "date_format": "%Y.%m.%d"
    },
    {
        "id": "glico", "name": "江崎グリコ", "category": "お菓子",
        "url": "https://www.glico.com/jp/newscenter/",
        "scraper_type": "auto",
        "badge_color": "#E60012",
        "date_format": "%Y.%m.%d"
    },
    {
        "id": "morinaga", "name": "森永製菓", "category": "お菓子",
        "url": "https://www.morinaga.co.jp/company/newsrelease/",
        "scraper_type": "auto",
        "badge_color": "#FFD700",
        "date_format": "%Y年%m月%d日"
    },
    {
        "id": "fujiya", "name": "不二家", "category": "お菓子",
        "url": "https://www.fujiya-peko.co.jp/company/news/",
        "scraper_type": "auto",
        "badge_color": "#006400",
        "date_format": "%Y.%m.%d"
    },

    # --- 冷凍食品メーカー ---
    {
        "id": "nichirei_2026", "name": "ニチレイフーズ(2026)", "category": "冷凍食品",
        "url": "https://www.nichirei.co.jp/news/2026/foods.html",
        "scraper_type": "auto",
        "badge_color": "#E60012",
        "date_format": "%Y.%m.%d"
    },
    {
        "id": "nichirei_2025", "name": "ニチレイフーズ(2025)", "category": "冷凍食品",
        "url": "https://www.nichirei.co.jp/news/2025/foods.html",
        "scraper_type": "auto",
        "badge_color": "#E60012",
        "date_format": "%Y.%m.%d"
    },
    {
        "id": "nissui", "name": "ニッスイ", "category": "冷凍食品",
        "url": "https://www.nissui.co.jp/news/index.html",
        "scraper_type": "auto",
        "badge_color": "#004DA0",
        "date_format": "%Y.%m.%d"
    },
    {
        "id": "ajinomoto_frozen", "name": "味の素冷凍食品", "category": "冷凍食品",
        "url": "https://news.ajinomoto.co.jp/", 
        "scraper_type": "auto",
        "badge_color": "#EA5514",
        "date_format": "%Y年%m月%d日"
    },
    {
        "id": "maruha", "name": "マルハニチロ", "category": "冷凍食品",
        "url": "https://www.maruha-nichiro.co.jp/corporate/news_center/news_topics/",
        "scraper_type": "auto",
        "badge_color": "#0067C0",
        "date_format": "%Y.%m.%d"
    },
    {
        "id": "tablemark", "name": "テーブルマーク", "category": "冷凍食品",
        "url": "https://www.tablemark.co.jp/corp/ir.html",
        "scraper_type": "auto",
        "badge_color": "#E60012",
        "date_format": "%Y.%m.%d"
    }
]