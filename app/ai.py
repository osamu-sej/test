"""Claude API による AI 機能(ダイジェスト生成・Q&A)。

収集済みニュースのタイトル一覧を根拠として、
- 業界動向の要約ダイジェスト(generate_digest)
- ユーザーの自由質問への回答(answer_question)
を生成する。API キー(ANTHROPIC_API_KEY)が設定されていない場合、
これらの機能は無効となり UI にも表示されない。

環境変数:
- ANTHROPIC_API_KEY   Claude API キー(必須。未設定なら機能オフ)
- NEWS_AI_MODEL       使用モデル(既定: claude-opus-4-8)
"""
import os

DEFAULT_MODEL = "claude-opus-4-8"

# プロンプトに含める最大ニュース件数(入力トークンの暴走防止)
MAX_ITEMS = 200

DIGEST_SYSTEM_PROMPT = """あなたは日本の小売業界(コンビニ・スーパー・ドラッグストア・食品メーカー等)を専門とするアナリストです。
各社の公式ニュースリリースのタイトル一覧から、業界動向のダイジェストを作成します。

出力ルール:
- 日本語で、プレーンテキストのみ(Markdown 記法は使わない)
- セクション見出しは【 】で囲む。箇条書きは「・」を使う
- 構成: 【本日のハイライト】(重要ニュース3〜5件を重要度順に、なぜ重要かを一言添えて)→【トピック別動向】(新商品/キャンペーン、店舗・出店、値上げ・価格、サステナ、DX など、該当があるものだけ)→【注目ポイント】(複数社に共通する動き・業界への示唆を2〜3行)
- タイトルから確実に読み取れる内容だけを書き、推測で事実を補わない
- 全体で600字〜900字程度に収める"""

QA_SYSTEM_PROMPT = """あなたは日本の小売業界(コンビニ・スーパー・ドラッグストア・食品メーカー等)を専門とするアナリストです。
各社の公式ニュースリリースのタイトル一覧を根拠として、ユーザーからの質問に答えます。

出力ルール:
- 日本語で、プレーンテキストのみ(Markdown 記法は使わない)
- 回答の根拠となるニュースは「[日付] 企業名: タイトル」の形で挙げる
- タイトル一覧から読み取れないことは、推測で補わず「提供されたニュースからは判断できません」と明示する
- ニュースと無関係な質問には、この期間の収集済みニュースについて答える役割であることを短く伝える
- 簡潔に、全体で400字程度までに収める"""


class AIDigestError(Exception):
    """ユーザーに表示するための AI 生成エラー。"""


def is_enabled() -> bool:
    return bool(os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN"))


def model_name() -> str:
    return os.environ.get("NEWS_AI_MODEL", DEFAULT_MODEL)


def _items_lines(items, start_date, end_date):
    lines = [f"対象期間: {start_date} 〜 {end_date}", f"ニュース件数: {len(items)}件", "", "--- ニュース一覧 ---"]
    for it in items[:MAX_ITEMS]:
        lines.append(f"[{it['date']}] {it['company_name']}: {it['title']}")
    if len(items) > MAX_ITEMS:
        lines.append(f"(ほか {len(items) - MAX_ITEMS} 件は省略)")
    return lines


def _call_claude(system_prompt, user_prompt) -> str:
    """Claude API を呼び出して本文テキストを返す。失敗時は AIDigestError を送出する。"""
    # anthropic ライブラリは重いため、実際に生成する瞬間まで読み込まない
    # (AI 機能を使わない環境での常駐メモリを節約する)
    import anthropic

    client = anthropic.Anthropic()
    try:
        response = client.messages.create(
            model=model_name(),
            max_tokens=16000,
            thinking={"type": "adaptive"},
            system=system_prompt,
            messages=[{"role": "user", "content": user_prompt}],
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
        raise AIDigestError("この内容には回答できませんでした。期間や対象企業、質問内容を変えて再試行してください。")

    text = next((b.text for b in response.content if b.type == "text"), "")
    if not text.strip():
        raise AIDigestError("生成結果が空でした。再試行してください。")
    return text.strip()


def generate_digest(items, start_date, end_date) -> str:
    """ニュース項目のリストからダイジェスト本文(プレーンテキスト)を生成する。
    失敗時は AIDigestError を送出する。"""
    lines = _items_lines(items, start_date, end_date)
    lines.append("")
    lines.append("上記のニュース一覧から業界動向ダイジェストを作成してください。")
    return _call_claude(DIGEST_SYSTEM_PROMPT, "\n".join(lines))


def answer_question(question, items, start_date, end_date) -> str:
    """収集済みニュースを根拠に、ユーザーの質問への回答を生成する。
    失敗時は AIDigestError を送出する。"""
    lines = _items_lines(items, start_date, end_date)
    lines.append("")
    lines.append("--- 質問 ---")
    lines.append(question)
    return _call_claude(QA_SYSTEM_PROMPT, "\n".join(lines))
