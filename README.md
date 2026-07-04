# Retail News Scout

小売・食品メーカー各社の公式ニュースリリースを日付範囲で横断チェックする FastAPI 製の Web アプリです。requests + BeautifulSoup で各社のニュースページをスクレイピングし、結果を 1 枚の HTML ページとして表示します。

## 起動方法

```bash
pip install -r requirements.txt
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

ブラウザで `http://localhost:8000/` を開くと、サイドバーで企業を選択して日付範囲でニュースを検索できます。

GitHub Codespaces では同梱の devcontainer が依存関係を自動インストールし、ポート **8000** が自動でフォワードされます。

## 構成

| パス | 内容 |
| ---- | ---- |
| `app/main.py` | FastAPI ルーティングと UI 生成 |
| `app/scraper.py` | `NewsScraper`(各社サイトの並列スクレイピング) |
| `app/service.py` | 収集オーケストレーション(SQLite キャッシュの鮮度判断) |
| `app/storage.py` | SQLite 永続化層(ニュース履歴と収集記録) |
| `app/scheduler.py` | 定時自動収集(バックグラウンドスレッド) |
| `app/companies.py` | 収集対象企業(コンビニ / スーパー / ドラッグストア / ディスカウント / 飲料 / お菓子 / 冷凍食品)の定義 |
| `app/templates/` `app/static/` | 画面テンプレート(Jinja2)と JS/CSS |
| `tests/` | API・キャッシュ層のテスト |

## AI ダイジェスト(オプション)

環境変数 `ANTHROPIC_API_KEY` を設定してサーバーを起動すると、サイドバーに
「AI ダイジェスト」ボタンが表示され、収集済みニュースから Claude が業界動向の
要約を生成します(未設定ならこの機能は表示されず、他の機能に影響はありません)。

| 変数 | 既定値 | 説明 |
| ---- | ------ | ---- |
| `ANTHROPIC_API_KEY` | (なし) | Claude API キー。設定すると AI ダイジェストが有効化 |
| `NEWS_AI_MODEL` | `claude-opus-4-8` | ダイジェスト生成に使うモデル |

生成結果は同一条件で30分間キャッシュされ、API 利用コストを抑えます。

## データと自動収集

- 収集結果は SQLite(既定: `data/news.db`)に蓄積され、キャッシュが新しい間は
  再スクレイピングせず即応答します(画面の「収集: MM/DD HH:MM」が収集時刻)
- サーバー起動中はバックグラウンドで定期収集が走ります
- サイドバーの「キャッシュを無視して再収集」でいつでも強制再収集できます

主な環境変数:

| 変数 | 既定値 | 説明 |
| ---- | ------ | ---- |
| `NEWS_DB_PATH` | `data/news.db` | SQLite ファイルの場所 |
| `NEWS_SCHEDULER` | `on` | `off` で定時収集を無効化 |
| `NEWS_SCHEDULER_INTERVAL` | `1800` | 定時収集の間隔(秒) |
| `NEWS_TTL_TODAY` / `NEWS_TTL_PAST` / `NEWS_TTL_ERROR` | `1800` / `86400` / `300` | キャッシュ鮮度(秒) |

## エンドポイント

| Method | Path | 説明 |
| ------ | ---- | ---- |
| GET | `/` | 検索 UI と結果を含む HTML を返す。クエリ: `start_date`, `end_date`(`YYYY-MM-DD`)、`companies`(複数指定可) |

データは取得の都度スクレイピングされ、永続化は行いません。

## テスト / CI

```bash
pytest
```

GitHub Actions が push / pull request ごとに `pytest` を実行します([`.github/workflows/ci.yml`](.github/workflows/ci.yml))。
