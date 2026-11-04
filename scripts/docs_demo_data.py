"""Fill a THROWAWAY SQLite database with made-up data for the documentation screenshots.

    DATABASE_URL=sqlite:////tmp/loupebox-docs.db python -m scripts.docs_demo_data

Everything here is invented (example.com addresses, fictional people). It refuses to run against anything
but SQLite so it can never touch a real database. Used by scripts/docs_screenshots.mjs.
"""
import sys
from datetime import UTC, date, datetime, timedelta

from app.core.audit import audit
from app.core.config import settings
from app.core.security import hash_password
from app.db.base import Base
from app.db.session import get_engine, get_sessionmaker
from app.models import (
    Feedback,
    FeedbackNote,
    FeedbackReply,
    FeedbackStatus,
    FeedbackTag,
    Membership,
    NotificationChannel,
    Role,
    Site,
    SiteStat,
    User,
)
from app.models.stats import StatKind

PASSWORD = "demo-password-123"
NOW = datetime.now(UTC).replace(microsecond=0)

PEOPLE = [  # first, last, email, superadmin
    ("Alex", "Rivera", "alex@example.com", True),
    ("Maya", "Chen", "maya@example.com", False),
    ("Sam", "Okafor", "sam@example.com", False),
    ("Priya", "Nair", "priya@example.com", False),
]

# hours ago, issue type, rating, name, email, message, status, assignee index (into PEOPLE), tags
DOCS_FEEDBACK = [
    (2, "bug", 2, "Jordan Lee", "jordan@example.org", "The search box on the install page does nothing when I press Enter on my phone.", "new", None, []),
    (5, "idea", 5, "Ines Duarte", "ines@example.org", "Could the code samples have a copy button? I keep selecting too much by accident.", "new", 1, ["docs"]),
    (9, "question", None, "Tom Baker", None, "Does the widget work on a site that uses a strict Content-Security-Policy?", "new", None, []),
    (20, "praise", 5, "Noor Hassan", "noor@example.org", "The setup guide worked first time. Thank you for writing it in plain language.", "read", None, []),
    (27, "bug", 3, "Chris Walker", "chris@example.org", "Page 'Webhooks' says the signature header is X-Signature but my requests show a different name.", "read", 2, ["docs", "needs-review"]),
    (31, "idea", 4, None, None, "A dark mode for the examples page would be easier on the eyes at night.", "new", None, []),
    (50, "question", None, "Lena Fischer", "lena@example.org", "How long are old feedback messages kept? Is there a way to delete them all?", "read", 1, []),
    (74, "bug", 1, "Mateo Silva", "mateo@example.org", "The download link for the PDF guide gives a 404.", "read", 2, ["broken-link"]),
    (96, "praise", 5, "Aiko Tanaka", None, "Clear and short. Exactly what I needed.", "archived", None, []),
    (120, "idea", 4, "Ben Carter", "ben@example.org", "Please add a printable version of the quick start.", "read", None, ["docs"]),
    (150, "question", None, "Zoe Adams", "zoe@example.org", "Is there an offline copy of these docs?", "archived", None, []),
    (190, "bug", 2, "Omar Said", "omar@example.org", "The menu covers the text on a small tablet in portrait mode.", "archived", 1, ["mobile"]),
    (240, "praise", 4, "Eva Novak", None, "Great examples. The curl one saved me an hour.", "archived", None, []),
    (300, "idea", 3, "Hugo Martin", "hugo@example.org", "A link back to the top of long pages would help.", "read", None, []),
]
SPAM = [(40, "BUY CHEAP WATCHES http://a.example http://b.example http://c.example http://d.example")]

APP_FEEDBACK = [
    (3, "bug", 2, "Riley Park", "riley@example.org", "The app logs me out every time I rotate my phone.", "new", None, []),
    (14, "idea", 5, "Dana Cole", None, "Please add a widget for the home screen.", "read", None, []),
    (60, "praise", 5, "Kai Moreno", "kai@example.org", "Fast and tidy. Best app of its kind I have used.", "read", None, []),
]


def main() -> None:
    if not settings.database_url.startswith("sqlite"):
        sys.exit("Refusing to run: DATABASE_URL must be a throwaway SQLite database.")
    Base.metadata.create_all(get_engine())
    with get_sessionmaker()() as db:
        users = []
        for first, last, email, is_super in PEOPLE:
            u = User(first_name=first, last_name=last, email=email, is_superadmin=is_super,
                     password_hash=hash_password(PASSWORD), created_at=NOW - timedelta(days=40))
            db.add(u)
            users.append(u)
        admin, maya, sam, priya = users

        docs = Site(name="Acme Docs", public_key="pk_demo_acme_docs_0000000000000000", daily_limit=200,
                    allowed_origins=["https://docs.acme.example", "http://localhost:3000"],
                    created_at=NOW - timedelta(days=30))
        app = Site(name="Acme Mobile App", public_key="pk_demo_acme_app_00000000000000000", daily_limit=200,
                   allowed_origins=["https://app.acme.example"], created_at=NOW - timedelta(days=12))
        db.add_all([docs, app])
        db.flush()
        for site, members in ((docs, [(maya, Role.editor), (sam, Role.editor), (priya, Role.viewer)]),
                              (app, [(maya, Role.admin)])):
            for user, role in members:
                db.add(Membership(user_id=user.id, site_id=site.id, role=role))

        def add_feedback(site, rows, page):
            made = []
            for hours, kind, rating, name, email, message, status, assignee, tags in rows:
                fb = Feedback(
                    site_id=site.id, message=message, rating=rating, name=name, email=email,
                    page_url=page, meta={"issue_type": kind} if kind else {}, status=FeedbackStatus(status),
                    content_hash=f"h{len(message)}{hours}", ip_hash="demo", created_at=NOW - timedelta(hours=hours),
                    assignee_id=users[assignee].id if assignee is not None else None,
                )
                db.add(fb)
                db.flush()
                db.add_all(FeedbackTag(feedback_id=fb.id, tag=t) for t in tags)
                made.append(fb)
            return made

        made = add_feedback(docs, DOCS_FEEDBACK, "https://docs.acme.example/install")
        for hours, text in SPAM:
            add_feedback(docs, [(hours, None, None, None, None, text, "spam", None, [])], "https://docs.acme.example/")
        add_feedback(app, APP_FEEDBACK, "https://app.acme.example/settings")

        # The item the "detail" and "reply" screenshots show: it has notes and a sent reply.
        item = made[4]
        db.add(FeedbackNote(feedback_id=item.id, author_id=maya.id, body="Checked: the header is X-Loupebox-Signature. The docs page is wrong.", created_at=NOW - timedelta(hours=22)))
        db.add(FeedbackNote(feedback_id=item.id, author_id=sam.id, body="I will fix the page today.", created_at=NOW - timedelta(hours=20)))
        db.add(FeedbackReply(feedback_id=item.id, author_id=sam.id, body="Thanks for spotting this. You are right, and the page is now fixed.", status="sent", created_at=NOW - timedelta(hours=3)))
        db.add(FeedbackNote(feedback_id=made[7].id, author_id=maya.id, body="The file was renamed. Updating the link.", created_at=NOW - timedelta(hours=60)))

        db.add(NotificationChannel(site_id=docs.id, provider="smtp", name="Team inbox", enabled=True, config={},
                                   events=["feedback.created"], min_role=Role.editor,
                                   extra_recipients=["team@example.com"]))

        # A fortnight of dropped-submission counts for the Activity tab.
        for back in range(14):
            day = date.today() - timedelta(days=back)
            for kind, base in ((StatKind.honeypot, 1 if back % 2 == 0 else 0), (StatKind.duplicate, 1 if back % 5 == 0 else 0),
                               (StatKind.rate_limited, 2 if back % 6 == 0 else 0), (StatKind.origin_denied, 1 if back % 4 == 0 else 0)):
                if base:
                    db.add(SiteStat(site_id=docs.id, day=day, kind=kind.value, count=base))

        audit(db, admin, "site.create", "Created site Acme Docs", target_type="site", target_id=docs.id, site=docs)
        audit(db, admin, "member.add", "Added maya@example.com as editor", target_type="site", target_id=docs.id, site=docs)
        audit(db, admin, "member.add", "Added priya@example.com as viewer", target_type="site", target_id=docs.id, site=docs)
        audit(db, admin, "channel.create", "Added notification channel Team inbox", target_type="site", target_id=docs.id, site=docs)
        audit(db, maya, "feedback.reply", "Replied to feedback", target_type="feedback", target_id=item.id, site=docs)
        db.commit()
    print(f"Demo data ready. Sign in as alex@example.com / {PASSWORD}")


if __name__ == "__main__":
    main()
