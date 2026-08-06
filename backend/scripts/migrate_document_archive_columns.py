from pathlib import Path
import sys

from sqlalchemy import inspect, text

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.db.session import engine  # noqa: E402

TABLE_NAME = "receiving_documents"
# ALTER TABLE ADD COLUMN, not Base.metadata.create_all() -- the latter only
# creates missing tables, not new columns on an existing one.
NEW_COLUMNS = {
    "archive_url": "VARCHAR(1000)",
    "archive_key": "VARCHAR(1000)",
    "archived_at": "TIMESTAMP",
}


def main() -> None:
    inspector = inspect(engine)
    if TABLE_NAME not in inspector.get_table_names():
        raise RuntimeError(
            f"Таблица '{TABLE_NAME}' не найдена -- сначала должна быть создана обычной инициализацией БД."
        )
    existing_columns = {col["name"] for col in inspector.get_columns(TABLE_NAME)}
    missing = {name: ddl_type for name, ddl_type in NEW_COLUMNS.items() if name not in existing_columns}
    if not missing:
        print(f"'{TABLE_NAME}' уже содержит все колонки архива документов -- ничего не сделано.")
        return

    with engine.begin() as connection:
        for name, ddl_type in missing.items():
            connection.execute(text(f"ALTER TABLE {TABLE_NAME} ADD COLUMN {name} {ddl_type}"))

    print(f"Добавлены колонки в '{TABLE_NAME}': {', '.join(sorted(missing))}.")


if __name__ == "__main__":
    main()
