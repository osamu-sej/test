"""環境変数の安全な読み取り。

運用者向けの調整用パラメータ(収集間隔・並列数・キャッシュ鮮度など)に
不正な値が設定されても、アプリの起動や収集が止まらないようにする:
- 数値に変換できない値(空文字など)→ 既定値にフォールバック
- 下限を下回る値 → 下限に切り上げ
"""
import os


def env_int(name, default, minimum=None):
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return default
    if minimum is not None:
        value = max(minimum, value)
    return value
