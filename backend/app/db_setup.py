import os
import sqlite3
from pathlib import Path

DEFAULT_DB_PATH = Path(__file__).resolve().parent.parent / "data" / "demo.db"

SEED_PRODUCTS = [
    (
        1,
        "Starter package",
        "Essential agentic RAG features for individuals and small teams.",
        100.0,
        "Subscriptions",
    ),
    (
        2,
        "Professional package",
        "Advanced analytics, priority support, and multi-tool MCP connectors.",
        500.0,
        "Subscriptions",
    ),
    (
        3,
        "Enterprise package",
        "Full platform access, custom MCP integrations, dedicated account manager, and SLA.",
        5000.0,
        "Subscriptions",
    ),
    (
        4,
        "Add-on Storage 1TB",
        "High-performance cloud storage volume for persistent conversation memory.",
        50.0,
        "Add-ons",
    ),
    (
        5,
        "Premium 24/7 Support",
        "Round-the-clock direct phone and chat technical support from senior engineers.",
        250.0,
        "Services",
    ),
]


def init_demo_database(db_path: str | Path | None = None) -> str:
    """Create and seed the demonstration SQLite database.

    Args:
        db_path: Optional explicit filesystem path. Defaults to SQLITE_DB_PATH env var
                 or backend/data/demo.db.

    Returns:
        Absolute string path to the initialized database file.
    """
    if db_path is None:
        env_path = os.getenv("SQLITE_DB_PATH")
        if env_path:
            db_path = Path(env_path)
            if not db_path.is_absolute():
                db_path = Path(__file__).resolve().parent.parent / env_path
        else:
            db_path = DEFAULT_DB_PATH

    path = Path(db_path).resolve()
    path.parent.mkdir(parents=True, exist_ok=True)

    with sqlite3.connect(path) as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS products (
                id INTEGER PRIMARY KEY,
                name TEXT NOT NULL UNIQUE,
                description TEXT,
                price REAL NOT NULL,
                category TEXT NOT NULL
            )
            """
        )

        for item in SEED_PRODUCTS:
            cursor.execute(
                """
                INSERT INTO products (id, name, description, price, category)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    name = excluded.name,
                    description = excluded.description,
                    price = excluded.price,
                    category = excluded.category
                """,
                item,
            )
        conn.commit()

    return str(path)


if __name__ == "__main__":
    resolved_path = init_demo_database()
    print(f"Demo SQLite database initialized at: {resolved_path}")
