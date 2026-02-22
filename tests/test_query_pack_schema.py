import json, os
from jsonschema import validate

def test_query_pack_schema():
    root = os.path.dirname(os.path.dirname(__file__))
    q = json.load(open(os.path.join(root, "config", "query_pack.json"), encoding="utf-8"))
    sch = json.load(open(os.path.join(root, "schemas", "query_pack.schema.json"), encoding="utf-8"))
    validate(q, sch)
