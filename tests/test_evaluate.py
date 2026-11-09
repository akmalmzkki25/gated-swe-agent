import json

from track3 import evaluate


def _report(logs, run_id, iid, resolved):
    d = logs / run_id / "model" / iid
    d.mkdir(parents=True)
    (d / "report.json").write_text(json.dumps({iid: {"resolved": resolved}}))
    (d / "test_output.txt").write_text("output")


def test_instances_without_a_harness_report_count_as_unresolved(tmp_path, monkeypatch):
    logs = tmp_path / "logs"
    monkeypatch.setattr(evaluate, "HARNESS_LOGS", logs)
    monkeypatch.setattr(evaluate, "ROOT", tmp_path)
    _report(logs, "r1", "a", True)
    _report(logs, "r1", "b", False)
    out = tmp_path / "eval"

    resolved = evaluate.collect("r1", out, expected=["a", "b", "c"], reasons={"c": "empty patch"})

    assert resolved == {"a": True, "b": False, "c": False}
    assert json.loads((out / "resolved.json").read_text()) == resolved
    assert json.loads((out / "unscored.json").read_text()) == {"c": "empty patch"}
    assert (out / "a" / "test_output.txt").exists()


def test_unexpected_missing_report_gets_a_generic_reason(tmp_path, monkeypatch):
    logs = tmp_path / "logs"
    monkeypatch.setattr(evaluate, "HARNESS_LOGS", logs)
    monkeypatch.setattr(evaluate, "ROOT", tmp_path)
    _report(logs, "r2", "a", True)
    evaluate.collect("r2", tmp_path / "eval", expected=["a", "z"])
    assert "no harness report" in json.loads((tmp_path / "eval" / "unscored.json").read_text())["z"]


def test_missing_reasons_from_predictions(tmp_path):
    preds = tmp_path / "preds.jsonl"
    preds.write_text(
        json.dumps({"instance_id": "a", "model_patch": "diff"}) + "\n" + json.dumps({"instance_id": "b", "model_patch": ""}) + "\n"
    )
    ids, reasons = evaluate.expected_from_preds(preds)
    assert ids == ["a", "b"] and reasons == {"b": "empty patch (the harness does not run it)"}
