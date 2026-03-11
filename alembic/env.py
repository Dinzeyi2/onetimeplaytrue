import os
from logging.config import fileConfig
from sqlalchemy import engine_from_config, pool
from alembic import context

config = context.config

raw_url = os.environ.get("DATABASE_URL", "")
# Alembic uses sync psycopg2 driver — strip asyncpg if present, normalize prefix
if raw_url.startswith("postgres://"):
    url = raw_url.replace("postgres://", "postgresql://", 1)
elif raw_url.startswith("postgresql+asyncpg://"):
    url = raw_url.replace("postgresql+asyncpg://", "postgresql://", 1)
else:
    url = raw_url

config.set_main_option("sqlalchemy.url", url)
if config.config_file_name: fileConfig(config.config_file_name)

import sys; sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from main import Base
target_metadata = Base.metadata

def run_migrations_offline():
    context.configure(url=url, target_metadata=target_metadata, literal_binds=True)
    with context.begin_transaction(): context.run_migrations()

def run_migrations_online():
    conn = engine_from_config(config.get_section(config.config_ini_section), prefix="sqlalchemy.", poolclass=pool.NullPool)
    with conn.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction(): context.run_migrations()

if context.is_offline_mode(): run_migrations_offline()
else: run_migrations_online()
