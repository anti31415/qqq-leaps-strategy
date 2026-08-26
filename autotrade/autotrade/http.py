from __future__ import annotations

import json
import ssl
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any


@dataclass
class HttpResponse:
    status: int
    data: Any
    headers: dict[str, str]


class HttpClient:
    def __init__(self, verify_ssl: bool = True) -> None:
        self.verify_ssl = verify_ssl

    def request(
        self,
        method: str,
        url: str,
        headers: dict[str, str] | None = None,
        params: dict[str, Any] | None = None,
        json_body: dict[str, Any] | None = None,
    ) -> HttpResponse:
        if params:
            query = urllib.parse.urlencode({k: v for k, v in params.items() if v is not None}, doseq=True)
            join = "&" if "?" in url else "?"
            url = f"{url}{join}{query}"

        body = None
        request_headers = {"Accept": "application/json", **(headers or {})}
        if json_body is not None:
            body = json.dumps(json_body).encode("utf-8")
            request_headers["Content-Type"] = "application/json"

        request = urllib.request.Request(url=url, method=method.upper(), headers=request_headers, data=body)
        context = None if self.verify_ssl else ssl._create_unverified_context()
        try:
            with urllib.request.urlopen(request, context=context, timeout=30) as response:
                payload = response.read().decode("utf-8")
                return HttpResponse(
                    status=response.status,
                    data=json.loads(payload) if payload else None,
                    headers=dict(response.headers.items()),
                )
        except urllib.error.HTTPError as exc:
            payload = exc.read().decode("utf-8")
            try:
                data = json.loads(payload) if payload else None
            except json.JSONDecodeError:
                data = {"raw": payload}
            raise RuntimeError(f"HTTP {exc.code} for {url}: {data}") from exc

