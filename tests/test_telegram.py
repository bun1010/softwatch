from softwatch.notify import telegram


class Resp:
    def __init__(self, code):
        self.status_code = code


def test_skipped_without_secrets_and_no_call():
    calls = []
    assert telegram.send("hello", "", "", post=lambda *a, **k: calls.append(1)).startswith("skipped")
    assert calls == []


def test_empty_text_is_not_sent():
    assert telegram.send("   ", "t", "c", post=lambda *a, **k: Resp(200)).startswith("skipped")


def test_sends_to_bot_endpoint_with_chat_id_and_link_preview_on():
    seen = {}

    def post(url, data, timeout):
        seen.update(url=url, data=data)
        return Resp(200)

    assert telegram.send("see <https://github.com/a/b>", "TOK", "123", post=post) == "sent"
    assert seen["url"] == "https://api.telegram.org/botTOK/sendMessage"
    assert seen["data"]["chat_id"] == "123"
    assert seen["data"]["disable_web_page_preview"] == "false"


def test_failure_does_not_leak_token():
    out = telegram.send("hi", "SECRET", "1", post=lambda *a, **k: Resp(401))
    assert out == "failed: Telegram HTTP 401"
    assert "SECRET" not in out


def test_long_text_is_split_on_lines():
    text = "\n".join("x" * 100 for _ in range(100))  # about 10,000 characters
    parts = telegram.chunks(text)
    assert len(parts) >= 3
    assert all(len(p) <= telegram.LIMIT for p in parts)
    assert "".join(parts) == text
