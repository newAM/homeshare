import uuid
from datetime import datetime, timedelta, timezone

from flask import Flask

from homeshare.models import Share, ShareLink, db


def test_share_round_trip(app: Flask) -> None:
    with app.app_context():
        share = Share(
            filename="hello.txt",
            stored_path="/var/lib/homeshare/uploads/abc123",
            owner="testuser",
        )
        db.session.add(share)
        db.session.commit()

        fetched = db.session.get(Share, share.share_id)
        assert fetched is not None
        assert fetched.filename == "hello.txt"
        assert fetched.stored_path == "/var/lib/homeshare/uploads/abc123"
        assert fetched.owner == "testuser"
        assert isinstance(fetched.created_at, datetime)


def test_share_uuid_primary_key(app: Flask) -> None:
    with app.app_context():
        share = Share(
            filename="file.txt",
            stored_path="/var/lib/homeshare/uploads/ghi789",
            owner="testuser",
        )
        db.session.add(share)
        db.session.commit()

        assert isinstance(share.share_id, uuid.UUID)


def test_share_to_dict(app: Flask) -> None:
    with app.app_context():
        share = Share(
            filename="file.txt",
            stored_path="/var/lib/homeshare/uploads/abc",
            owner="testuser",
        )
        db.session.add(share)
        db.session.commit()

        link = ShareLink(share_id=share.share_id, expires_in=3600)
        db.session.add(link)
        db.session.commit()

        d = share.to_dict()
        assert d["share_id"] == str(share.share_id)
        assert d["filename"] == "file.txt"
        assert len(d["links"]) == 1
        assert d["links"][0]["link_id"] == str(link.link_id)


def test_link_round_trip(app: Flask) -> None:
    with app.app_context():
        share = Share(
            filename="file.txt",
            stored_path="/var/lib/homeshare/uploads/abc",
            owner="testuser",
        )
        db.session.add(share)
        db.session.commit()

        link = ShareLink(
            share_id=share.share_id,
            label="for Alice",
            expires_in=7200,
        )
        db.session.add(link)
        db.session.commit()

        fetched = db.session.execute(
            db.select(ShareLink).where(ShareLink.link_id == link.link_id)
        ).scalar_one()
        assert fetched.share_id == share.share_id
        assert fetched.label == "for Alice"
        assert fetched.expires_in == 7200
        assert fetched.download_count == 0


def test_link_download_count(app: Flask) -> None:
    with app.app_context():
        share = Share(
            filename="file.txt",
            stored_path="/var/lib/homeshare/uploads/abc",
            owner="testuser",
        )
        db.session.add(share)
        db.session.commit()

        link = ShareLink(share_id=share.share_id)
        db.session.add(link)
        db.session.commit()

        link.download_count += 1
        db.session.commit()

        fetched = db.session.execute(
            db.select(ShareLink).where(ShareLink.link_id == link.link_id)
        ).scalar_one()
        assert fetched.download_count == 1


def test_link_not_expired_when_no_expiry(app: Flask) -> None:
    with app.app_context():
        share = Share(
            filename="forever.txt",
            stored_path="/var/lib/homeshare/uploads/xyz789",
            owner="testuser",
        )
        db.session.add(share)
        db.session.commit()

        link = ShareLink(share_id=share.share_id)
        db.session.add(link)
        db.session.commit()

        assert not link.is_expired


def test_link_not_expired_when_future_expiry(app: Flask) -> None:
    with app.app_context():
        share = Share(
            filename="future.txt",
            stored_path="/var/lib/homeshare/uploads/fut123",
            owner="testuser",
        )
        db.session.add(share)
        db.session.commit()

        link = ShareLink(
            share_id=share.share_id,
            created_at=datetime.now(timezone.utc),
            expires_in=86400,
        )
        db.session.add(link)
        db.session.commit()

        assert not link.is_expired


def test_link_is_expired_when_past_expiry(app: Flask) -> None:
    with app.app_context():
        share = Share(
            filename="expired.txt",
            stored_path="/var/lib/homeshare/uploads/exp456",
            owner="testuser",
        )
        db.session.add(share)
        db.session.commit()

        link = ShareLink(
            share_id=share.share_id,
            created_at=datetime.now(timezone.utc) - timedelta(hours=2),
            expires_in=3600,
        )
        db.session.add(link)
        db.session.commit()

        assert link.is_expired
