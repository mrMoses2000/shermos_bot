from pathlib import Path


def test_json_integrity_migration_repairs_and_constrains_core_jsonb_fields():
    sql = Path("migrations/014_json_integrity_and_relations.sql").read_text(encoding="utf-8")

    for table_field in (
        "conversation_state",
        "inbound_events",
        "outbound_events",
        "orders",
        "prices",
        "materials",
    ):
        assert table_field in sql
    assert "_shermos_unwrap_jsonb" in sql
    assert "jsonb_typeof(collected_params) = 'object'" in sql
    assert "jsonb_typeof(raw_update) = 'object'" in sql
    assert "jsonb_typeof(details_json) = 'object'" in sql


def test_json_integrity_migration_adds_real_foreign_keys_for_order_flow():
    sql = Path("migrations/014_json_integrity_and_relations.sql").read_text(encoding="utf-8")

    assert "FOREIGN KEY (telegram_update_id)" in sql
    assert "FOREIGN KEY (chat_id)" in sql
    assert "REFERENCES processed_updates(telegram_update_id)" in sql
    assert "REFERENCES clients(chat_id)" in sql


def test_order_drafts_migration_links_active_collection_to_final_order():
    sql = Path("migrations/015_order_drafts.sql").read_text(encoding="utf-8")

    assert "CREATE TABLE IF NOT EXISTS order_drafts" in sql
    assert "REFERENCES clients(chat_id)" in sql
    assert "REFERENCES orders(request_id)" in sql
    assert "idx_order_drafts_one_active_per_chat" in sql
    assert "jsonb_typeof(collected_params) = 'object'" in sql
