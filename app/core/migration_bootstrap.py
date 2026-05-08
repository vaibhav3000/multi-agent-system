from sqlalchemy import create_engine, inspect, text

from app.core.database import DATABASE_URL, _sync_database_url


def main() -> None:
    engine = create_engine(_sync_database_url(DATABASE_URL), pool_pre_ping=True)
    with engine.begin() as conn:
        inspector = inspect(conn)
        tables = set(inspector.get_table_names())
        if "alembic_version" in tables or "jobs" not in tables:
            return
        conn.execute(text("CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL PRIMARY KEY)"))
        conn.execute(text("INSERT INTO alembic_version (version_num) VALUES ('20260508_0001')"))


if __name__ == "__main__":
    main()

