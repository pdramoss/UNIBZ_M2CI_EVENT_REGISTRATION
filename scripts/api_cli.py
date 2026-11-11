#!/usr/bin/env python3
import argparse
import getpass
import json
import os
import sys
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


class APIError(Exception):
    pass


def send_request(
    base_url: str,
    method: str,
    path: str,
    payload: dict[str, object] | None = None,
    token: str | None = None,
) -> object | None:
    headers = {"Accept": "application/json"}
    if token is not None:
        headers["Authorization"] = f"Bearer {token}"

    body = None
    if payload is not None:
        body = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"

    request = Request(
        f"{base_url.rstrip('/')}{path}",
        data=body,
        headers=headers,
        method=method,
    )
    try:
        with urlopen(request, timeout=20) as response:
            response_body = response.read()
    except HTTPError as error:
        error_body = error.read()
        try:
            error_detail = json.loads(error_body).get("detail", error_body.decode())
        except json.JSONDecodeError:
            error_detail = error_body.decode()
        raise APIError(f"HTTP {error.code}: {error_detail}") from error

    if not response_body:
        return None
    try:
        return json.loads(response_body)
    except json.JSONDecodeError as error:
        raise APIError("The API returned an invalid JSON response") from error


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Manage accounts, events, and registrations through the HTTP API."
    )
    parser.add_argument(
        "--base-url",
        default=os.environ.get("API_BASE_URL", "http://127.0.0.1:8000"),
        help="API server base URL (default: %(default)s)",
    )
    resources = parser.add_subparsers(dest="resource", required=True)

    auth_parser = resources.add_parser("auth")
    auth_operations = auth_parser.add_subparsers(
        dest="operation", required=True
    )
    login_parser = auth_operations.add_parser("login")
    login_parser.add_argument("--username", required=True)
    auth_operations.add_parser("logout")

    for resource in ("clients", "administrators"):
        resource_parser = resources.add_parser(resource)
        operations = resource_parser.add_subparsers(dest="operation", required=True)
        create_parser = operations.add_parser("create")
        create_parser.add_argument(
            "--data", required=True, help="Account fields as a JSON object"
        )

    for resource in ("users", "events", "registrations"):
        resource_parser = resources.add_parser(resource)
        operations = resource_parser.add_subparsers(dest="operation", required=True)

        list_parser = operations.add_parser("list")
        list_parser.add_argument("--limit", type=int, default=100)
        list_parser.add_argument("--offset", type=int, default=0)

        get_parser = operations.add_parser("get")
        get_parser.add_argument("id", type=int)

        create_parser = operations.add_parser("create")
        create_parser.add_argument(
            "--data", required=True, help="Request fields as a JSON object"
        )

        update_parser = operations.add_parser("update")
        update_parser.add_argument("id", type=int)
        update_parser.add_argument(
            "--data", required=True, help="Fields to update as a JSON object"
        )

        delete_parser = operations.add_parser("delete")
        delete_parser.add_argument("id", type=int)

    return parser


def _parse_payload(
    parser: argparse.ArgumentParser, raw_payload: str
) -> dict[str, object]:
    try:
        payload = json.loads(raw_payload)
    except json.JSONDecodeError as error:
        parser.error(f"--data must contain valid JSON: {error.msg}")
    if not isinstance(payload, dict):
        parser.error("--data must be a JSON object")
    return payload


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    payload = None
    token = None

    if args.resource == "auth":
        method = "POST"
        if args.operation == "login":
            path = "/api/v1/auth/login"
            payload = {
                "username": args.username,
                "password": getpass.getpass("Password: "),
            }
        else:
            path = "/api/v1/auth/logout"
            token = os.environ.get("API_TOKEN")
            if not token:
                parser.error("auth logout requires API_TOKEN")
    else:
        collection_path = f"/api/v1/{args.resource}"
        if args.operation == "list":
            path = f"{collection_path}?limit={args.limit}&offset={args.offset}"
            method = "GET"
        elif args.operation == "get":
            path = f"{collection_path}/{args.id}"
            method = "GET"
        elif args.operation == "create":
            path = collection_path
            method = "POST"
            payload = _parse_payload(parser, args.data)
        elif args.operation == "update":
            path = f"{collection_path}/{args.id}"
            method = "PATCH"
            payload = _parse_payload(parser, args.data)
        else:
            path = f"{collection_path}/{args.id}"
            method = "DELETE"

        requires_token = args.resource in {"clients", "administrators"} or (
            args.resource == "events"
            and args.operation in {"create", "update", "delete"}
        ) or args.resource == "registrations"
        if requires_token:
            token = os.environ.get("API_TOKEN")
            if not token:
                parser.error("this command requires API_TOKEN; log in first")

    try:
        result = send_request(
            args.base_url, method, path, payload, token=token
        )
    except APIError as error:
        parser.exit(1, f"API error: {error}\n")
    except URLError as error:
        parser.exit(1, f"Could not connect to API: {error.reason}\n")

    if args.resource == "auth" and args.operation == "login":
        if not isinstance(result, dict) or not isinstance(
            result.get("access_token"), str
        ):
            parser.exit(1, "API error: login response did not contain an access token\n")
        print(result["access_token"])
    elif args.resource == "auth":
        print("Logged out")
    elif result is None:
        print(f"{args.resource[:-1]} {args.id} deleted")
    else:
        json.dump(result, sys.stdout, indent=2)
        sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
