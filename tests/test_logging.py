import io
import json
import logging

from sie.logging_setup import REDACTED, configure_logging, get_logger, redact


def capture(json_output=True):
    stream = io.StringIO()
    configure_logging("DEBUG", json_output=json_output, stream=stream)
    return stream


def last(stream) -> dict:
    return json.loads(stream.getvalue().strip().splitlines()[-1])


def test_json_line_has_core_fields():
    stream = capture()
    get_logger("sie.test").info("hello %s", "world")
    record = last(stream)
    assert record["message"] == "hello world"
    assert record["level"] == "INFO"
    assert record["logger"] == "sie.test"
    assert record["ts"].endswith("+00:00")


def test_extra_fields_are_included():
    stream = capture()
    get_logger("sie.test").info("fetched", extra={"source_id": 17, "count": 3})
    record = last(stream)
    assert record["source_id"] == 17 and record["count"] == 3


def test_secret_looking_fields_are_redacted():
    stream = capture()
    get_logger("sie.test").info(
        "login",
        extra={
            "api_hash": "abc",
            "session_file": "x.session",
            "nested": {"password": "p", "ok": 1},
        },
    )
    record = last(stream)
    assert record["api_hash"] == REDACTED
    assert record["session_file"] == REDACTED
    assert record["nested"] == {"password": REDACTED, "ok": 1}
    assert "abc" not in json.dumps(record)


def test_redact_handles_lists_and_plain_values():
    assert redact([{"token": "t"}, 5]) == [{"token": REDACTED}, 5]
    assert redact("plain", key="source") == "plain"


def test_exception_is_serialised():
    stream = capture()
    try:
        raise ValueError("boom")
    except ValueError:
        get_logger("sie.test").exception("failed")
    assert "ValueError: boom" in last(stream)["exc"]


def test_configure_is_idempotent():
    stream = capture()
    stream2 = capture()
    get_logger("sie.test").info("once")
    ours = [h for h in logging.getLogger().handlers if getattr(h, "_sie_handler", False)]
    assert len(ours) == 1
    assert stream.getvalue() == ""  # the first handler was replaced
    assert "once" in stream2.getvalue()


def test_plain_format():
    stream = capture(json_output=False)
    get_logger("sie.test").warning("careful")
    assert "WARNING" in stream.getvalue() and "careful" in stream.getvalue()
