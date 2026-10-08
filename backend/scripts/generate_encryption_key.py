"""Print a new field encryption key for FIELD_ENCRYPTION_KEY.

Usage: python -m scripts.generate_encryption_key [key_id]

To rotate, generate a key with a new id, set it as FIELD_ENCRYPTION_KEY and move the previous
value into FIELD_ENCRYPTION_OLD_KEYS (comma separated) so existing data stays readable.
"""

import sys

from app.core.crypto import generate_key


def main() -> None:
    key_id = sys.argv[1] if len(sys.argv) > 1 else "k1"
    print(generate_key(key_id))


if __name__ == "__main__":
    main()
