import pytest

from app.agent import build_sql_query, is_database_query


@pytest.mark.parametrize(
    "query, expected",
    [
        ("How do I plant tomatoes?", False),
        ("Explain the support vector machine algorithm", False),
        ("Tell me a story about a service dog", False),
        ("What is the plan for tomorrow?", False),
        ("What is your workout plan?", False),
        ("How do I make a lesson plan?", False),
        ("Can you help plan a trip to Paris?", False),
        ("Tell me about the capital of France", False),
        ("How much is the Enterprise plan?", True),
        ("What support tiers exist?", True),
        ("Compare Starter and Professional pricing", True),
        ("What is the price of the Starter package?", True),
        ("Show me the products catalog", True),
        ("How much does storage cost?", True),
        ("What are the pricing details?", True),
        ("Show all available products from the database", True),
        ("Query database for subscription options", True),
    ],
)
def test_is_database_query_routing(query: str, expected: bool) -> None:
    assert is_database_query(query) == expected


def test_build_sql_query_compound_multiple_products() -> None:
    sql, term = build_sql_query("price of enterprise and starter")
    assert "LOWER(name) LIKE '%enterprise%'" in sql
    assert "LOWER(name) LIKE '%starter%'" in sql
    assert " OR " in sql
    assert "enterprise" in term and "starter" in term

    sql2, term2 = build_sql_query("Compare Starter and Professional pricing")
    assert "LOWER(name) LIKE '%starter%'" in sql2
    assert "LOWER(name) LIKE '%professional%'" in sql2
    assert " OR " in sql2
    assert "starter" in term2 and "professional" in term2


def test_build_sql_query_single_product() -> None:
    sql, term = build_sql_query("What is the price of the Enterprise package?")
    assert sql == "SELECT id, name, description, price, category FROM products WHERE LOWER(name) LIKE '%enterprise%'"
    assert term == "enterprise"


def test_build_sql_query_unknown_package() -> None:
    sql, term = build_sql_query("What is the price of the Quantum package?")
    assert sql == "SELECT id, name, description, price, category FROM products WHERE LOWER(name) LIKE '%quantum%'"
    assert term == "quantum"


def test_build_sql_query_all_products() -> None:
    sql, term = build_sql_query("Show all available products")
    assert sql == "SELECT id, name, description, price, category FROM products"
    assert term is None


def test_build_sql_query_sanitizes_injection() -> None:
    sql, term = build_sql_query("'; DROP TABLE products;-- plan")
    assert "DROP" not in sql.upper()
    assert ";" not in sql
    assert "--" not in sql
    assert sql.strip().upper().startswith("SELECT")
