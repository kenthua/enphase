import json
import sys

from enphase_client import EnphaseCloudClient


def main() -> int:
    client = EnphaseCloudClient()
    result = client.get_status()
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
