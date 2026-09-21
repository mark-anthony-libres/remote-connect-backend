
def Sync(func: str | list[str], exec_after: str = None, groups=None, truncate_before_sync: bool = False):
    def decorator(cls):
        cls._sync_func = func if isinstance(func, (list, tuple)) else [func]
        if exec_after:
            cls._sync_exec_after = exec_after
        cls._sync_truncate_before_sync = truncate_before_sync
        if groups:
            cls._sync_groups = groups
        return cls
    return decorator


def SyncAlias(alias: str):
    def decorator(func):
        func._sync_alias = alias
        return func
    return decorator