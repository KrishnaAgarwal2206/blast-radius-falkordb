import time

import httpx


def _retry(fn, tries=5):
    for i in range(tries):
        try:
            return fn()
        except (httpx.HTTPError, OSError):
            if i == tries - 1:
                raise
            time.sleep(1.5 * (i + 1))


def get(url, **kw):
    return _retry(lambda: httpx.get(url, timeout=kw.pop("timeout", 90), follow_redirects=True, **kw))


def post(url, **kw):
    return _retry(lambda: httpx.post(url, timeout=kw.pop("timeout", 90), **kw))
