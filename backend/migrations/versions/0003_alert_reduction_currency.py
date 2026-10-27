"""Allow currency for reduction-only alert rules."""

from alembic import op

revision = "0003_alert_reduction_currency"
down_revision = "0002_execution_targets"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("alert_rules") as batch_op:
        batch_op.drop_constraint(
            "ck_alert_rules_target_currency_consistency", type_="check"
        )
        batch_op.create_check_constraint(
            "target_currency_consistency",
            "target_amount_minor IS NULL OR currency IS NOT NULL",
        )


def downgrade() -> None:
    with op.batch_alter_table("alert_rules") as batch_op:
        batch_op.drop_constraint(
            "ck_alert_rules_target_currency_consistency", type_="check"
        )
        batch_op.create_check_constraint(
            "target_currency_consistency",
            "(target_amount_minor IS NULL AND currency IS NULL) OR "
            "(target_amount_minor IS NOT NULL AND currency IS NOT NULL)",
        )
