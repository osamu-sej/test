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
| `app/main.py` | FastAPI アプリ本体。`NewsScraper`(スクレイピング)と HTML 生成、`GET /` エンドポイント |
| `app/companies.py` | 収集対象企業(コンビニ / スーパー / ドラッグストア / ディスカウント / 飲料 / お菓子 / 冷凍食品)の定義 |
| `tests/test_api.py` | `fetch_news` をモックした API テスト |

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
