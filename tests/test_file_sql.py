"""Unit tests for DuckDB file SQL naming and validation."""

from pathlib import Path

from app.tools.file_sql import (
    discover_file_tables,
    table_name_for_file,
    validate_file_sql,
)


def test_table_name_for_file_prefixes_and_slugs():
    assert table_name_for_file("Sales Data", "reports/Q1.csv") == "sales_data_reports_q1"
    assert table_name_for_file("a", "x.tsv") == "a_x"


def test_validate_file_sql_allows_select():
    assert validate_file_sql("SELECT * FROM sales_data_q1 LIMIT 5") is None
    assert validate_file_sql("WITH t AS (SELECT 1 AS n) SELECT * FROM t") is None


def test_validate_file_sql_blocks_writes_and_duckdb_ext():
    assert validate_file_sql("DELETE FROM t") is not None
    assert validate_file_sql("INSTALL httpfs") is not None
    assert validate_file_sql("LOAD excel") is not None
    assert validate_file_sql("ATTACH 's3://bucket/x' AS remote") is not None
    assert validate_file_sql("SELECT * FROM read_csv('https://evil')") is not None


def test_discover_file_tables_prefixes_by_source(tmp_path: Path):
    root_a = tmp_path / "src_a"
    root_b = tmp_path / "src_b"
    root_a.mkdir()
    root_b.mkdir()
    (root_a / "orders.csv").write_text("id,qty\n1,2\n", encoding="utf-8")
    (root_b / "orders.csv").write_text("id,qty\n3,4\n", encoding="utf-8")
    mounts = {
        "sources/aaa": root_a,
        "sources/bbb": root_b,
    }
    tables = discover_file_tables(
        mounts,
        source_titles={"aaa": "Warehouse", "bbb": "Retail"},
    )
    names = {t["table"] for t in tables}
    assert "warehouse_orders" in names
    assert "retail_orders" in names
    assert names == {"warehouse_orders", "retail_orders"}
