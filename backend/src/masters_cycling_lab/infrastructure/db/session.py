from sqlalchemy import Engine, create_engine


def make_engine(database_url: str) -> Engine:
    # pool_pre_ping replaces connections that died, for example after the database restarted.
    return create_engine(database_url, pool_pre_ping=True, connect_args={"connect_timeout": 5})
