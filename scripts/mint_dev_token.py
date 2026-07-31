import argparse
from typing import TypedDict

from services.common.settings import PermissionProxySettings
from services.permission_proxy.security.auth import AccessTokenService


class TokenDefaults(TypedDict):
    subject: str
    scopes: set[str]


TOKEN_DEFAULTS: dict[str, TokenDefaults] = {
    "agent": {
        "subject": "dev:agent_support_001",
        "scopes": {"tool:invoke"},
    },
    "host": {
        "subject": "dev:trusted-host",
        "scopes": {"session:create", "session:revoke"},
    },
    "admin": {
        "subject": "dev:administrator",
        "scopes": {
            "session:create",
            "session:revoke",
            "manifest:admin",
            "audit:read",
        },
    },
    "auditor": {
        "subject": "dev:auditor",
        "scopes": {"audit:read"},
    },
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Mint a short-lived local access token when development auth is enabled"
    )
    parser.add_argument(
        "--type",
        choices=sorted(TOKEN_DEFAULTS),
        required=True,
        dest="token_type",
    )
    parser.add_argument("--subject", help="Override the default token subject")
    parser.add_argument(
        "--scope",
        action="append",
        dest="scopes",
        help="Override scopes; pass this option once per scope",
    )
    parser.add_argument("--ttl-seconds", type=int, default=900)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.ttl_seconds < 60 or args.ttl_seconds > 3600:
        raise ValueError("--ttl-seconds must be between 60 and 3600")

    defaults = TOKEN_DEFAULTS[args.token_type]
    subject = args.subject or defaults["subject"]
    scopes = set(args.scopes) if args.scopes else defaults["scopes"]
    settings = PermissionProxySettings()
    token = AccessTokenService(settings).issue_development_token(
        subject=subject,
        token_use=args.token_type,
        scopes=scopes,
        ttl_seconds=args.ttl_seconds,
    )
    print(token)


if __name__ == "__main__":
    main()
