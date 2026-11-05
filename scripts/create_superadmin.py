"""Create (or promote) the first superadmin: python -m scripts.create_superadmin you@example.com"""

import getpass
import sys

from sqlalchemy import select

from app.core.security import hash_password
from app.db.session import get_sessionmaker
from app.models import User


def main() -> None:
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    email = sys.argv[1].lower()
    first = input("First name: ").strip()
    last = input("Last name: ").strip()
    if not first or not last:
        sys.exit("Names are required")
    password = getpass.getpass("Password (min 12 chars): ")
    if len(password) < 12:
        sys.exit("Password too short")
    with get_sessionmaker()() as db:
        user = db.scalar(select(User).where(User.email == email))
        if user is None:
            user = User(first_name=first, last_name=last, email=email, password_hash=hash_password(password))
            db.add(user)
        else:
            user.password_hash = hash_password(password)
            user.first_name, user.last_name = first, last
        user.is_superadmin = True
        db.commit()
    print(f"Superadmin ready: {email}")


if __name__ == "__main__":
    main()
