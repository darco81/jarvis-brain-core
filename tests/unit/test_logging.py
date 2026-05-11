import json
from io import StringIO

from brain.core.logging import configure_logging, get_logger


def test_log_output_is_json_with_fields() -> None:
    buf = StringIO()
    configure_logging(level="INFO", stream=buf)
    log = get_logger("test")
    log.info("event.name", repo="example-front-a", files=7)
    line = buf.getvalue().strip().splitlines()[-1]
    data = json.loads(line)
    assert data["event"] == "event.name"
    assert data["repo"] == "example-front-a"
    assert data["files"] == 7
    assert data["level"] == "info"
