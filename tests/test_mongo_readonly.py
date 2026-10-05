"""Unit tests for MongoDB read-only allowlist / block guards."""

from app.tools.mongo_readonly import validate_mongo_filter, validate_mongo_pipeline


def test_filter_allows_simple_equality():
    assert validate_mongo_filter({"status": "active"}) is None
    assert validate_mongo_filter({"age": {"$gte": 18}}) is None


def test_filter_blocks_where_and_function():
    assert validate_mongo_filter({"$where": "this.a > 1"}) is not None
    assert validate_mongo_filter({"x": {"$function": {"body": "1"}}}) is not None


def test_pipeline_allows_match_group():
    pipeline = [
        {"$match": {"status": "ok"}},
        {"$group": {"_id": "$region", "n": {"$sum": 1}}},
        {"$limit": 10},
    ]
    assert validate_mongo_pipeline(pipeline) is None


def test_pipeline_blocks_out_and_merge():
    assert validate_mongo_pipeline([{"$out": "other"}]) is not None
    assert validate_mongo_pipeline([{"$merge": {"into": "t"}}]) is not None
    assert (
        validate_mongo_pipeline(
            [{"$match": {"a": 1}}, {"$merge": {"into": "sink"}}]
        )
        is not None
    )


def test_pipeline_rejects_non_list_and_bad_stages():
    assert validate_mongo_pipeline({"$match": {}}) is not None
    assert validate_mongo_pipeline([{"$match": {}, "$limit": 1}]) is not None
    assert validate_mongo_pipeline([{"match": {}}]) is not None
