"""Create the initial PriceWatch persistence schema."""

from alembic import op
import sqlalchemy as sa

revision = "0001_initial_schema"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "stores",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("slug", sa.String(length=80), nullable=False),
        sa.Column("base_domain", sa.String(length=253), nullable=False),
        sa.Column("integration_status", sa.String(length=20), nullable=False),
        sa.Column("is_enabled", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "integration_status IN ('pending', 'tested', 'active', 'disabled')",
            name=op.f("ck_stores_integration_status"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_stores")),
        sa.UniqueConstraint("base_domain", name=op.f("uq_stores_base_domain")),
        sa.UniqueConstraint("slug", name=op.f("uq_stores_slug")),
    )
    op.create_table(
        "products",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=240), nullable=False),
        sa.Column("canonical_key", sa.String(length=160), nullable=False),
        sa.Column("brand", sa.String(length=120), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_products")),
        sa.UniqueConstraint("canonical_key", name=op.f("uq_products_canonical_key")),
    )
    op.create_table(
        "product_variants",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("product_id", sa.Integer(), nullable=False),
        sa.Column("variant_key", sa.String(length=160), nullable=False),
        sa.Column("label", sa.String(length=240), nullable=False),
        sa.Column("attributes", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["product_id"], ["products.id"], ondelete="CASCADE",
            name=op.f("fk_product_variants_product_id_products"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_product_variants")),
        sa.UniqueConstraint("product_id", "variant_key", name="uq_variant_product_key"),
    )
    op.create_table(
        "store_listings",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("store_id", sa.Integer(), nullable=False),
        sa.Column("product_id", sa.Integer(), nullable=False),
        sa.Column("variant_id", sa.Integer(), nullable=True),
        sa.Column("external_id", sa.String(length=160), nullable=True),
        sa.Column("url", sa.String(length=2048), nullable=False),
        sa.Column("title", sa.String(length=500), nullable=True),
        sa.Column("is_enabled", sa.Boolean(), nullable=False),
        sa.Column("validation_status", sa.String(length=20), nullable=False),
        sa.Column("extraction_method", sa.String(length=40), nullable=True),
        sa.Column("last_checked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "validation_status IN ('pending', 'valid', 'invalid')",
            name=op.f("ck_store_listings_validation_status"),
        ),
        sa.ForeignKeyConstraint(
            ["product_id"], ["products.id"], ondelete="CASCADE",
            name=op.f("fk_store_listings_product_id_products"),
        ),
        sa.ForeignKeyConstraint(
            ["store_id"], ["stores.id"], ondelete="RESTRICT",
            name=op.f("fk_store_listings_store_id_stores"),
        ),
        sa.ForeignKeyConstraint(
            ["variant_id"], ["product_variants.id"], ondelete="SET NULL",
            name=op.f("fk_store_listings_variant_id_product_variants"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_store_listings")),
        sa.UniqueConstraint("store_id", "external_id", name="uq_listing_store_external"),
        sa.UniqueConstraint("url", name=op.f("uq_store_listings_url")),
    )
    op.create_table(
        "price_observations",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("listing_id", sa.Integer(), nullable=False),
        sa.Column("amount_minor", sa.Integer(), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("availability", sa.String(length=20), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("is_valid", sa.Boolean(), nullable=False),
        sa.Column("extraction_method", sa.String(length=40), nullable=False),
        sa.Column("source_reference", sa.String(length=2048), nullable=True),
        sa.CheckConstraint("amount_minor > 0", name=op.f("ck_price_observations_positive_amount")),
        sa.CheckConstraint("length(currency) = 3", name=op.f("ck_price_observations_currency_length")),
        sa.CheckConstraint(
            "availability IN ('in_stock', 'out_of_stock', 'unknown')",
            name=op.f("ck_price_observations_availability"),
        ),
        sa.ForeignKeyConstraint(
            ["listing_id"], ["store_listings.id"], ondelete="CASCADE",
            name=op.f("fk_price_observations_listing_id_store_listings"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_price_observations")),
    )
    op.create_table(
        "shipping_quotes",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("listing_id", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("amount_minor", sa.Integer(), nullable=True),
        sa.Column("currency", sa.String(length=3), nullable=True),
        sa.Column("source", sa.String(length=120), nullable=False),
        sa.Column("quoted_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("status IN ('known', 'unknown')", name=op.f("ck_shipping_quotes_shipping_status")),
        sa.CheckConstraint(
            "(status = 'known' AND amount_minor IS NOT NULL AND amount_minor >= 0 "
            "AND currency IS NOT NULL) OR "
            "(status = 'unknown' AND amount_minor IS NULL)",
            name=op.f("ck_shipping_quotes_shipping_amount_consistency"),
        ),
        sa.CheckConstraint(
            "currency IS NULL OR length(currency) = 3",
            name=op.f("ck_shipping_quotes_currency_length"),
        ),
        sa.ForeignKeyConstraint(
            ["listing_id"], ["store_listings.id"], ondelete="CASCADE",
            name=op.f("fk_shipping_quotes_listing_id_store_listings"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_shipping_quotes")),
    )
    op.create_table(
        "alert_rules",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("product_id", sa.Integer(), nullable=False),
        sa.Column("variant_id", sa.Integer(), nullable=True),
        sa.Column("target_amount_minor", sa.Integer(), nullable=True),
        sa.Column("currency", sa.String(length=3), nullable=True),
        sa.Column("minimum_reduction_basis_points", sa.Integer(), nullable=True),
        sa.Column("detect_new_cheapest", sa.Boolean(), nullable=False),
        sa.Column("notification_interval_hours", sa.Integer(), nullable=False),
        sa.Column("is_enabled", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "target_amount_minor IS NULL OR target_amount_minor > 0",
            name=op.f("ck_alert_rules_target_amount"),
        ),
        sa.CheckConstraint(
            "(target_amount_minor IS NULL AND currency IS NULL) OR "
            "(target_amount_minor IS NOT NULL AND currency IS NOT NULL)",
            name=op.f("ck_alert_rules_target_currency_consistency"),
        ),
        sa.CheckConstraint(
            "currency IS NULL OR length(currency) = 3",
            name=op.f("ck_alert_rules_currency_length"),
        ),
        sa.CheckConstraint(
            "minimum_reduction_basis_points IS NULL OR "
            "minimum_reduction_basis_points BETWEEN 0 AND 10000",
            name=op.f("ck_alert_rules_reduction_range"),
        ),
        sa.CheckConstraint(
            "notification_interval_hours >= 0",
            name=op.f("ck_alert_rules_notification_interval"),
        ),
        sa.ForeignKeyConstraint(
            ["product_id"], ["products.id"], ondelete="CASCADE",
            name=op.f("fk_alert_rules_product_id_products"),
        ),
        sa.ForeignKeyConstraint(
            ["variant_id"], ["product_variants.id"], ondelete="CASCADE",
            name=op.f("fk_alert_rules_variant_id_product_variants"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_alert_rules")),
    )
    op.create_table(
        "alert_events",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("rule_id", sa.Integer(), nullable=False),
        sa.Column("deduplication_key", sa.String(length=255), nullable=False),
        sa.Column("event_type", sa.String(length=40), nullable=False),
        sa.Column("state", sa.String(length=20), nullable=False),
        sa.Column("triggered_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.CheckConstraint(
            "state IN ('pending', 'notified', 'dismissed')",
            name=op.f("ck_alert_events_alert_state"),
        ),
        sa.ForeignKeyConstraint(
            ["rule_id"], ["alert_rules.id"], ondelete="CASCADE",
            name=op.f("fk_alert_events_rule_id_alert_rules"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_alert_events")),
        sa.UniqueConstraint(
            "deduplication_key", name="uq_alert_deduplication_key"
        ),
    )
    op.create_table(
        "execution_runs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("trigger", sa.String(length=20), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("listings_checked", sa.Integer(), nullable=False),
        sa.Column("listings_succeeded", sa.Integer(), nullable=False),
        sa.Column("listings_failed", sa.Integer(), nullable=False),
        sa.Column("error_summary", sa.Text(), nullable=True),
        sa.CheckConstraint(
            "status IN ('running', 'succeeded', 'partial', 'failed')",
            name=op.f("ck_execution_runs_execution_status"),
        ),
        sa.CheckConstraint(
            "trigger IN ('manual', 'scheduled')",
            name=op.f("ck_execution_runs_execution_trigger"),
        ),
        sa.CheckConstraint("listings_checked >= 0", name=op.f("ck_execution_runs_listings_checked_nonnegative")),
        sa.CheckConstraint("listings_succeeded >= 0", name=op.f("ck_execution_runs_listings_succeeded_nonnegative")),
        sa.CheckConstraint("listings_failed >= 0", name=op.f("ck_execution_runs_listings_failed_nonnegative")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_execution_runs")),
    )


def downgrade() -> None:
    op.drop_table("execution_runs")
    op.drop_table("alert_events")
    op.drop_table("alert_rules")
    op.drop_table("shipping_quotes")
    op.drop_table("price_observations")
    op.drop_table("store_listings")
    op.drop_table("product_variants")
    op.drop_table("products")
    op.drop_table("stores")
