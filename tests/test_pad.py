import base64
import json
import threading
import time
import urllib.error
import urllib.request

import pytest

from signpad.pad import PadServer


def call(pad, path, body=None, token=True, host=None):
    url = pad.url.split("/?")[0] + path + (f"?t={pad.token}" if token else "")
    req = urllib.request.Request(url, data=None if body is None else json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"})
    if host:
        req.add_header("Host", host)
    with urllib.request.urlopen(req, timeout=5) as r:
        return json.loads(r.read())


@pytest.fixture
def pad():
    p = PadServer(open_browser=False)
    p.start()
    yield p
    p.close()


def wait_phase(pad, phase):
    for _ in range(100):
        s = call(pad, "/api/state")
        if s["phase"] == phase:
            return s
        time.sleep(0.02)
    raise AssertionError(f"never reached {phase}")


def test_static_page_served(pad):
    with urllib.request.urlopen(pad.url.split("?")[0], timeout=5) as r:
        assert b"SignPad" in r.read()


def test_api_requires_token_and_local_host(pad):
    with pytest.raises(urllib.error.HTTPError) as e:
        call(pad, "/api/state", token=False)
    assert e.value.code == 403
    with pytest.raises(urllib.error.HTTPError) as e:
        call(pad, "/api/state", host="evil.example")
    assert e.value.code == 403


def test_signature_round_trip(pad, signature_png):
    got = {}
    t = threading.Thread(target=lambda: got.setdefault("png", pad.request_signature("Alex", "Sign it")))
    t.start()
    s = wait_phase(pad, "sign")
    assert s["signer"] == "Alex"
    data = "data:image/png;base64," + base64.b64encode(signature_png).decode()
    assert call(pad, "/api/submit", {"seq": s["seq"], "action": "signed", "png": data})["ok"]
    t.join(5)
    assert got["png"] == signature_png


def test_rejects_stale_and_bad_submissions(pad):
    t = threading.Thread(target=lambda: pad.request_signature("Alex", "Sign it"))
    t.start()
    s = wait_phase(pad, "sign")
    with pytest.raises(urllib.error.HTTPError) as e:
        call(pad, "/api/submit", {"seq": s["seq"] - 1, "action": "declined"})
    assert e.value.code == 409
    with pytest.raises(urllib.error.HTTPError) as e:
        call(pad, "/api/submit", {"seq": s["seq"], "action": "signed", "png": "data:image/png;base64,AAAA"})
    assert e.value.code == 400
    call(pad, "/api/submit", {"seq": s["seq"], "action": "declined"})
    t.join(5)


def test_review_round_trip(pad):
    got = {}
    t = threading.Thread(target=lambda: got.setdefault("r", pad.request_review("did x", b"%PDF-1.4", ["a.pdf"])))
    t.start()
    s = wait_phase(pad, "review")
    assert s["has_preview"] and s["files"] == ["a.pdf"]
    call(pad, "/api/submit", {"seq": s["seq"], "approved": False, "comment": "move it"})
    t.join(5)
    assert got["r"] == (False, "move it")
