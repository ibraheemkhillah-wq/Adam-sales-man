from functools import lru_cache

from app import config
from app.erp.base import ERPBackend


@lru_cache(maxsize=1)
def get_erp() -> ERPBackend:
    if config.ERP_BACKEND == "eganis":
        from app.erp.eganis import EganisERP

        return EganisERP()
    from app.erp.mock import MockERP

    return MockERP()
