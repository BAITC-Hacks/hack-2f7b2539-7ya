"""Small EKT API client for inspecting the partner-provided JSON responses."""

from __future__ import annotations

import argparse
import base64
import json
import os
import sys
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


class EKTAPIError(Exception):
    """An API error safe to display to the caller."""


def _required_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise EKTAPIError(f"Missing required environment variable: {name}")
    return value


def _request_json(path: str, params: dict[str, str] | None = None) -> Any:
    base_url = _required_env("EKT_API_BASE_URL").rstrip("/")
    username = _required_env("EKT_API_USERNAME")
    password = _required_env("EKT_API_PASSWORD")
    query = f"?{urlencode(params)}" if params else ""
    token = base64.b64encode(f"{username}:{password}".encode("utf-8")).decode("ascii")
    request = Request(
        f"{base_url}/{path.lstrip('/')}{query}",
        headers={"Authorization": f"Basic {token}", "Accept": "application/json"},
        method="GET",
    )
    try:
        with urlopen(request, timeout=30) as response:
            raw = response.read()
    except HTTPError as exc:
        if exc.code in (401, 403):
            raise EKTAPIError(
                f"Authentication/authorization failed (HTTP {exc.code}). Check EKT_API_USERNAME and EKT_API_PASSWORD."
            ) from None
        raise EKTAPIError(f"EKT API returned HTTP {exc.code}.") from None
    except URLError as exc:
        # Avoid exposing URLs or low-level error details that could contain sensitive data.
        reason_type = type(exc.reason).__name__
        raise EKTAPIError(f"Could not connect to the EKT API ({reason_type}).") from None
    except TimeoutError:
        raise EKTAPIError("The EKT API request timed out.") from None

    try:
        return json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise EKTAPIError("The EKT API response was not valid JSON.") from None


def get_products(page: int | None = None) -> Any:
    """Return the raw JSON value from GET /products (optionally ?page=N)."""
    params = {"page": str(page)} if page is not None else None
    return _request_json("products", params)


def get_product_detail(product_id: str) -> Any:
    """Return the raw JSON value from GET /products/detail?id=..."""
    return _request_json("products/detail", {"id": product_id})


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Inspect actual JSON returned by the EKT API.")
    subparsers = parser.add_subparsers(dest="command", required=True)
    products_parser = subparsers.add_parser("products", help="Fetch GET /products")
    products_parser.add_argument("--page", type=int, help="Optional page query parameter")
    detail_parser = subparsers.add_parser("detail", help="Fetch GET /products/detail?id=...")
    detail_parser.add_argument("id", help="Product ID")
    args = parser.parse_args(argv)

    try:
        result = get_products(args.page) if args.command == "products" else get_product_detail(args.id)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except EKTAPIError as exc:
        print(f"EKT API error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
