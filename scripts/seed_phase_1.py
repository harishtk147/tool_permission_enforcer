import argparse
import json

from services.common.database import Database
from services.common.settings import PermissionProxySettings
from services.permission_proxy.persistence.seed import seed_phase_1


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Seed deterministic Phase 1 synthetic data")
    parser.add_argument(
        "--database-url",
        help="Override PROXY_DATABASE_URL for this seed run",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    database_url = args.database_url or PermissionProxySettings().database_url
    database = Database(database_url)
    try:
        summary = seed_phase_1(database)
    finally:
        database.dispose()

    print(json.dumps(summary.__dict__, sort_keys=True))


if __name__ == "__main__":
    main()
