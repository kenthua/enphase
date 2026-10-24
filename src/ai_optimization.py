import json
import sys

from enphase_client import EnphaseCloudClient


def main() -> int:
    client = EnphaseCloudClient()
    result = client.set_ai_optimization()
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    sys.exit(main())
