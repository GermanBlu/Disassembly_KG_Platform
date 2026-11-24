"""The chat starter questions are served and identical in all three places.

No database is needed.
"""
import app as A


def test_chat_starters_are_served():
    resp = A.app.test_client().get("/api/chat/starters")
    assert resp.status_code == 200
    chips = resp.get_json()["starters"]
    assert chips and all(c.get("q") for c in chips)


def test_starter_lists_are_identical():
    """The chips of the catalogue, the fallback in app.py and the fallback in
    static/app.html are the same six questions."""
    import os
    import re
    served = [c["q"] for c in A.app.test_client().get("/api/chat/starters").get_json()["starters"]]
    fallback = [c["q"] for c in A._FALLBACK_STARTERS]
    html = open(os.path.join(os.path.dirname(A.__file__), "static", "app.html"), encoding="utf-8").read()
    block = re.search(r"let _STARTERS = \[(.*?)\];", html, re.DOTALL).group(1)
    in_page = re.findall(r"'([^']*)'", block)
    assert len(served) == 6
    assert served == fallback == in_page
