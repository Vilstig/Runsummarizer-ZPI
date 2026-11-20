from app.providers.intervals.activity_keys import intervals_activity_id, intervals_activity_key


def test_the_key_prefixes_the_activity_id():
    assert intervals_activity_key("i7") == "intervals_i7"
    assert intervals_activity_key(7) == "intervals_7"


def test_the_id_is_recovered_from_the_key():
    assert intervals_activity_id("intervals_i7") == "i7"
