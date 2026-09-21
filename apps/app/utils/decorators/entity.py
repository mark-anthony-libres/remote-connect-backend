def Entity():
    """
    Decorator to mark a class as a model entity. Does not modify class behavior.
    Adds _is_entity and _entity_name attributes for identification.
    """
    def decorator(cls):
        cls._is_entity = True
        cls._entity_name = cls.__name__

        table = getattr(cls, "__table__", None)

        if table is not None:
            table.info["entity_class"] = cls

        return cls
    return decorator
