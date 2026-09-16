import io
import json
import zipfile

import pytest

from backend.trace_parser import parse_trace_zip
from backend.zip_utils import TraceArchiveError


def archive(trace=None, network=None, extra=None):
    data = io.BytesIO()
    with zipfile.ZipFile(data, "w", zipfile.ZIP_DEFLATED) as value:
        if trace is not None: value.writestr("trace.trace", "\n".join(json.dumps(x) if not isinstance(x, str) else x for x in trace))
        if network is not None: value.writestr("trace.network", "\n".join(json.dumps(x) for x in network))
        for name, content in extra or []: value.writestr(name, content)
    return data.getvalue()


def test_extracts_actions_failure_errors_and_inventory():
    result = parse_trace_zip(archive([
        {"type":"before","callId":"x","apiName":"locator.click","startTime":10,"params":{"selector":"#pay","value":"small"}},
        "malformed", {"type":"future-record","unknown":True},
        {"type":"pageError","message":"boom","time":11},
        {"type":"after","callId":"x","endTime":20,"error":{"message":"Timeout 10ms exceeded"}},
    ], extra=[("resources/blob", b"binary")]))
    action = result["actions"][0]
    assert action["api_name"] == "locator.click" and action["selector"] == "#pay"
    assert action["error"] == "Timeout 10ms exceeded" and action["duration_ms"] == 10
    assert result["page_errors"][0]["message"] == "boom"
    assert result["inventory"]["resource_files_found"] == 1


def test_network_is_sanitized_and_headers_and_bodies_are_never_returned():
    record = {"snapshot":{"request":{"method":"GET","url":"https://example.test/x?token=secret","headers":[{"name":"Authorization","value":"Bearer secret"}],"postData":"password=x"},"response":{"status":500,"headers":[{"name":"Set-Cookie","value":"secret"}],"content":{"text":"secret"}}}}
    text = json.dumps(parse_trace_zip(archive([], [record])))
    assert "token=[REDACTED]" in text
    assert "Authorization" not in text and "Set-Cookie" not in text and "postData" not in text


@pytest.mark.parametrize("data,message", [(b"no", "valid ZIP"), (archive(extra=[]), "empty")])
def test_rejects_invalid_and_empty_zip(data, message):
    with pytest.raises(TraceArchiveError, match=message): parse_trace_zip(data)


def test_rejects_zip_without_trace_data():
    with pytest.raises(TraceArchiveError, match="no supported"):
        parse_trace_zip(archive(extra=[("readme.txt", "x")]))


def test_missing_optional_fields_do_not_crash():
    result = parse_trace_zip(archive([{"type":"action","apiName":"expect"}]))
    assert result["actions"][0]["start_time"] is None
