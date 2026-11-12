from sqlalchemy import Engine, create_engine

# gssencmode=disable: libpq otherwise tries Kerberos (GSSAPI) encryption first, which can stall a new connection for
# 5-20 seconds while it looks for credentials. Nothing here uses Kerberos.
CONNECT_ARGS = {"connect_timeout": 5, "gssencmode": "disable"}


def make_engine(database_url: str) -> Engine:
    # pool_pre_ping replaces connections that died, for example after the database restarted.
    return create_engine(database_url, pool_pre_ping=True, connect_args=CONNECT_ARGS)
