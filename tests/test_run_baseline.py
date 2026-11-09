import yaml

from track3.run_baseline import ROOT, baseline_override


def test_override_touches_only_model_and_budget():
    o = baseline_override(seed=1)
    assert set(o) == {"model", "agent"}
    assert set(o["agent"]) == {"step_limit", "cost_limit"}
    assert set(o["model"]) == {"model_name", "model_kwargs"}


def test_override_uses_pinned_model_budget_and_seed():
    model = yaml.safe_load((ROOT / "configs/model.yaml").read_text(encoding="utf-8"))
    budget = yaml.safe_load((ROOT / "configs/budget.yaml").read_text(encoding="utf-8"))
    o = baseline_override(seed=2)
    assert o["model"]["model_name"] == model["model_name"]
    assert o["model"]["model_kwargs"] == {**model["model_kwargs"], "seed": 2}
    assert o["agent"] == {"step_limit": budget["per_task"]["model_calls"], "cost_limit": budget["per_task"]["cost_usd"]}
