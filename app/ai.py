"""Claude API による AI ダイジェスト生成。

収集済みニュースのタイトル一覧から、その日の小売業界動向の
要約ダイジェストを生成する。API キー(ANTHROPIC_API_KEY)が
設定されていない場合、この機能は無効となり UI にも表示されない。

環境変数:
- ANTHROPIC_API_KEY   Claude API キー(必須。未設定なら機能オフ)
- NEWS_AI_MODEL       使用モデル(既定: claude-opus-4-8)
"""
import os

DEFAULT_MODEL = "claude-opus-4-8"

# ダイジェストに含める最大ニュース件数(入力トークンの暴走防止)
MAX_ITEMS = 200

SYSTEM_PROMPT = """あなたは日本の小売業界(コンビニ・スーパー・ドラッグストア・食品メーカー等)を専門とするアナリストです。
各社の公式ニュースリリースのタイトル一覧から、業界動向のダイジェストを作成します。

出力ルール:
- 日本語で、プレーンテキストのみ(Markdown 記法は使わない)
- セクション見出しは【 】で囲む。箇条書きは「・」を使う
- 構成: 【本日のハイライト】(重要ニュース3〜5件を重要度順に、なぜ重要かを一言添えて)→【トピック別動向】(新商品/キャンペーン、店舗・出店、値上げ・価格、サステナ、DX など、該当があるものだけ)→【注目ポイント】(複数社に共通する動き・業界への示唆を2〜3行)
- タイトルから確実に読み取れる内容だけを書き、推測で事実を補わない
- 全体で600字〜900字程度に収める"""


class AIDigestError(Exception):
    """ユーザーに表示するためのダイジェスト生成エラー。"""


def is_enabled() -> bool:
    return bool(os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN"))


def model_name() -> str:
    return os.environ.get("NEWS_AI_MODEL", DEFAULT_MODEL)


def _build_prompt(items, start_date, end_date):
    lines = [f"対象期間: {start_date} 〜 {end_date}", f"ニュース件数: {len(items)}件", "", "--- ニュース一覧 ---"]
    for it in items[:MAX_ITEMS]:
        lines.append(f"[{it['date']}] {it['company_name']}: {it['title']}")
    if len(items) > MAX_ITEMS:
        lines.append(f"(ほか {len(items) - MAX_ITEMS} 件は省略)")
    lines.append("")
    lines.append("上記のニュース一覧から業界動向ダイジェストを作成してください。")
    return "\n".join(lines)


def generate_digest(items, start_date, end_date) -> str:
    """ニュース項目のリストからダイジェスト本文(プレーンテキスト)を生成する。
    失敗時は AIDigestError を送出する。"""
    # anthropic ライブラリは重いため、実際にダイジェストを生成する瞬間まで
    # 読み込まない(AI 機能を使わない環境での常駐メモリを節約する)
    import anthropic

    client = anthropic.Anthropic()
    try:
        response = client.messages.create(
            model=model_name(),
            max_tokens=16000,
            thinking={"type": "adaptive"},
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": _build_prompt(items, start_date, end_date)}],
        )
    except anthropic.AuthenticationError:
        raise AIDigestError("Claude API キーが無効です。ANTHROPIC_API_KEY を確認してください。")
    except anthropic.RateLimitError:
        raise AIDigestError("Claude API のレート制限に達しました。しばらく待ってから再試行してください。")
    except anthropic.APIStatusError as exc:
        if exc.status_code >= 500:
            raise AIDigestError("Claude API が一時的に混雑しています。しばらく待ってから再試行してください。")
        raise AIDigestError(f"Claude API エラー ({exc.status_code}): {exc.message}")
    except anthropic.APIConnectionError:
        raise AIDigestError("Claude API に接続できません。サーバーのネットワーク設定を確認してください。")

    if response.stop_reason == "refusal":
        raise AIDigestError("この内容のダイジェストは生成できませんでした。期間や対象企業を変えて再試行してください。")

    text = next((b.text for b in response.content if b.type == "text"), "")
    if not text.strip():
        raise AIDigestError("ダイジェストの生成結果が空でした。再試行してください。")
    return text.strip()
