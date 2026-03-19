import json

from pokerbench_utils import build_action_json, parse_pokerbench_label


def test_parse_simple_actions():
    assert parse_pokerbench_label("Check") == ("check", None)
    assert parse_pokerbench_label("fold") == ("fold", None)
    assert parse_pokerbench_label("Call") == ("call", None)


def test_parse_raise_amount():
    action, amt = parse_pokerbench_label("Bet 7.5")
    assert action == "raise"
    assert amt == 7.5

    action, amt = parse_pokerbench_label("Raise10")
    assert action == "raise"
    assert abs(amt - 10.0) < 1e-6


def test_build_action_json_roundtrip():
    payload = json.loads(build_action_json("raise", 12))
    assert payload["action"] == "raise"
    assert payload["raise_amount"] == 12
    assert "reasoning" in payload
