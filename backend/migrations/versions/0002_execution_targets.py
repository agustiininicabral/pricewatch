"""Link update executions to optional product/listing scopes."""

from alembic import op
import sqlalchemy as sa

revision = "0002_execution_targets"
down_revision = "0001_initial_schema"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("execution_runs") as batch_op:
        batch_op.add_column(sa.Column("product_id", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("listing_id", sa.Integer(), nullable=True))
        batch_op.create_foreign_key(
            "fk_execution_runs_product_id_products",
            "products",
            ["product_id"],
            ["id"],
            ondelete="SET NULL",
        )
        batch_op.create_foreign_key(
            "fk_execution_runs_listing_id_store_listings",
            "store_listings",
            ["listing_id"],
            ["id"],
            ondelete="SET NULL",
        )


def downgrade() -> None:
    with op.batch_alter_table("execution_runs") as batch_op:
        batch_op.drop_constraint(
            "fk_execution_runs_listing_id_store_listings", type_="foreignkey"
        )
        batch_op.drop_constraint(
            "fk_execution_runs_product_id_products", type_="foreignkey"
        )
        batch_op.drop_column("listing_id")
        batch_op.drop_column("product_id")
