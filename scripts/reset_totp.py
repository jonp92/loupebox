"""Lockout recovery for two-factor authentication.

python -m scripts.reset_totp you@example.com    turn off 2FA for a user (signs them out everywhere)
python -m scripts.reset_totp --stop-requiring   drop the "Require two-factor authentication" override

With 2FA required, a user whose 2FA was reset signs in with their password and sets it up again.
--stop-requiring removes the setting saved on the System page; if REQUIRE_TOTP=true is in the
environment, remove that too.
"""

import sys

from sqlalchemy import delete, select

from app.core.accounts import clear_totp, revoke_sessions
from app.db.session import get_sessionmaker
from app.models import AppSetting, User


def main() -> None:
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    arg = sys.argv[1]
    with get_sessionmaker()() as db:
        if arg == "--stop-requiring":
            db.execute(delete(AppSetting).where(AppSetting.key == "require_totp"))
            db.commit()
            print("Removed the saved setting; the API picks it up within 30 seconds")
            return
        user = db.scalar(select(User).where(User.email == arg.lower()))
        if user is None:
            sys.exit(f"No such user: {arg}")
        clear_totp(db, user)
        revoke_sessions(db, user.id)
        db.commit()
    print(f"Two-factor authentication is off for {arg.lower()}; their sessions were signed out")


if __name__ == "__main__":
    main()
