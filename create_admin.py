# create_admin.py — Create or update the administrator (or any) user.
# The schema does not seed the admin user automatically; this script creates it securely (hashed).
# python create_admin.py ---- admin / admin123 (defaults)
# python create_admin.py admin StrongPass ---- custom password

import sys
from werkzeug.security import generate_password_hash
import db_standalone as dbs


def main():
    username = sys.argv[1] if len(sys.argv) > 1 else "admin"
    password = sys.argv[2] if len(sys.argv) > 2 else "admin123"

    conn = dbs.connect()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """INSERT INTO hfg_users (username, password_hash)
                   VALUES (%s, %s)
                   ON CONFLICT (username)
                   DO UPDATE SET password_hash = EXCLUDED.password_hash""",
                (username, generate_password_hash(password)),
            )
        conn.commit()
        print(f"User '{username}' created/updated.")
    finally:
        conn.close()


if __name__ == "__main__":
    main()