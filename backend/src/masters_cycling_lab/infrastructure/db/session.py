"""The database engine used by the API, the worker and the CLI."""

from sqlalchemy import Engine, create_engine

# connect_timeout: Docker Desktop occasionally stalls a new connection for several seconds.
# gssencmode=disable: libpq otherwise tries Kerberos (GSSAPI) encryption first, which can stall a new connection for
# 5-20 seconds while it looks for credentials. Nothing here uses Kerberos.
CONNECT_ARGS = {"connect_timeout": 15, "gssencmode": "disable"}


def make_engine(database_url: str) -> Engine:
    """A SQLAlchemy engine that replaces dead connections and gives up on a stalled connect after 15 s."""
    # pool_pre_ping replaces connections that died, for example after the database restarted.
    return create_engine(database_url, pool_pre_ping=True, connect_args=CONNECT_ARGS)
