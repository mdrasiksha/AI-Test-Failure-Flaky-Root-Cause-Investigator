import io
import zipfile

import pytest

import backend.zip_utils as limits
from backend.zip_utils import TraceArchiveError, open_safe_zip


def make(items):
    data=io.BytesIO()
    with zipfile.ZipFile(data,"w",zipfile.ZIP_DEFLATED) as archive:
        for name, value in items: archive.writestr(name,value)
    return data.getvalue()


@pytest.mark.parametrize("name", ["../escape.trace", "/absolute.trace", "C:/escape.trace", "dir\\..\\escape.trace"])
def test_path_traversal_is_rejected(name):
    with pytest.raises(TraceArchiveError, match="unsafe path"): open_safe_zip(make([(name,"{}")]))


def test_excessive_file_count(monkeypatch):
    monkeypatch.setattr(limits,"MAX_TRACE_FILES",1)
    with pytest.raises(TraceArchiveError, match="too many"): open_safe_zip(make([("a.trace","{}"),("b.trace","{}")]))


def test_excessive_uncompressed_size(monkeypatch):
    monkeypatch.setattr(limits,"MAX_TRACE_UNCOMPRESSED_MB",0)
    with pytest.raises(TraceArchiveError, match="uncompressed"): open_safe_zip(make([("a.trace","{}")]))
