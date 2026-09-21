
import sqlalchemy as sa
import json
from apps.app.utils import convert_string_none_to_null

class JsonCol(sa.TypeDecorator):

    impl = sa.Text
    cache_ok = True

    def process_bind_param(self, value, dialect):
        value = convert_string_none_to_null(value)
        if value is None:
            return None
        if isinstance(value, (dict, list)):
            return json.dumps(value)
        return value

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        try:
            return json.loads(value)
        except (TypeError, ValueError):
            return value
