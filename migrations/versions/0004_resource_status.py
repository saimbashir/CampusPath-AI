"""Background indexing status for uploaded resources (large books on small hosts)."""
from alembic import op
import sqlalchemy as sa
revision='0004'
down_revision='0003'
branch_labels=None
depends_on=None
def upgrade():
    op.add_column('resources',sa.Column('status',sa.String(20),nullable=False,server_default='ready'))
    op.add_column('resources',sa.Column('status_detail',sa.String(300),nullable=True))
def downgrade():
    with op.batch_alter_table('resources') as b:
        b.drop_column('status_detail');b.drop_column('status')
