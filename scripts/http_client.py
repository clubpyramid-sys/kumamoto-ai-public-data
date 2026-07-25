from __future__ import annotations

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


def make_session(http_config: dict) -> requests.Session:
    session = requests.Session()
    retries = int(http_config.get("retries", 3))
    retry = Retry(
        total=retries,
        connect=retries,
        read=retries,
        backoff_factor=0.8,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=frozenset({"GET", "HEAD"}),
        raise_on_status=False,
    )
    session.mount("https://", HTTPAdapter(max_retries=retry))
    session.headers.update({
        "User-Agent": http_config.get("user_agent", "KumamotoPublicDataBot/1.0"),
        "Accept-Language": "ja,en;q=0.8",
    })
    return session


def get_or_raise(session: requests.Session, url: str, timeout: int, **kwargs) -> requests.Response:
    response = session.get(url, timeout=timeout, **kwargs)
    response.raise_for_status()
    return response
