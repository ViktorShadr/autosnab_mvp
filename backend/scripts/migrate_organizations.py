from pathlib import Path
import sys

from sqlalchemy import inspect, text

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.db.session import Base, SessionLocal, engine  # noqa: E402
from app.models import *  # noqa: F401,F403,E402
from app.models.organization import Organization  # noqa: E402

DEFAULT_ORGANIZATION_NAME = "Кафе Ромашка"
DEFAULT_ORGANIZATION_SLUG = "cafe-romashka"

# ALTER TABLE ADD COLUMN on the pre-existing tables, not
# Base.metadata.create_all() -- that only creates the new `organizations`
# table, it does not add a column to a table that already exists.
BACKFILL_TABLES = {
    "receivings": "organization_id",
    "ingestion_uploads": "organization_id",
}


def _ensure_organization_id_columns() -> None:
    inspector = inspect(engine)
    with engine.begin() as connection:
        for table_name, column_name in BACKFILL_TABLES.items():
            if table_name not in inspector.get_table_names():
                continue
            existing_columns = {col["name"] for col in inspector.get_columns(table_name)}
            if column_name in existing_columns:
                continue
            connection.execute(text(f"ALTER TABLE {table_name} ADD COLUMN {column_name} INTEGER"))
            print(f"Добавлена колонка '{column_name}' в '{table_name}'.")


def _ensure_default_organization() -> Organization:
    session = SessionLocal()
    try:
        organization = (
            session.query(Organization).filter(Organization.slug == DEFAULT_ORGANIZATION_SLUG).first()
        )
        if organization is None:
            organization = Organization(name=DEFAULT_ORGANIZATION_NAME, slug=DEFAULT_ORGANIZATION_SLUG)
            session.add(organization)
            session.commit()
            session.refresh(organization)
            print(f"Создана организация '{DEFAULT_ORGANIZATION_NAME}' (id={organization.id}).")
        return organization
    finally:
        session.close()


def _backfill_organization_id(organization_id: int) -> None:
    with engine.begin() as connection:
        for table_name in BACKFILL_TABLES:
            result = connection.execute(
                text(f"UPDATE {table_name} SET organization_id = :org_id WHERE organization_id IS NULL"),
                {"org_id": organization_id},
            )
            print(f"'{table_name}': заполнено organization_id для {result.rowcount} строк.")


def main() -> None:
    Base.metadata.create_all(bind=engine)  # creates the new `organizations` table only
    _ensure_organization_id_columns()
    organization = _ensure_default_organization()
    _backfill_organization_id(organization.id)
    print("Готово.")


if __name__ == "__main__":
    main()
