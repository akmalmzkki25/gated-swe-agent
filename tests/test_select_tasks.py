import pytest

from track3.select_tasks import Cell, stratified_draw


def _row(iid, difficulty, repo):
    return {"instance_id": iid, "difficulty": difficulty, "repo": repo}


POOL = [
    _row("a__a-1", "easy", "a/a"),
    _row("a__a-2", "easy", "a/a"),
    _row("a__a-3", "easy", "a/a"),
    _row("b__b-1", "easy", "b/b"),
    _row("b__b-2", "hard", "b/b"),
    _row("b__b-3", "hard", "b/b"),
]


def test_same_seed_gives_same_draw():
    cells = [Cell("easy", "a/a", 2), Cell("hard", "b/b", 1)]
    assert stratified_draw(POOL, cells, seed=42) == stratified_draw(POOL, cells, seed=42)


def test_draw_ignores_input_order():
    cells = [Cell("easy", "a/a", 2), Cell("hard", "b/b", 1)]
    assert stratified_draw(POOL, cells, seed=42) == stratified_draw(list(reversed(POOL)), cells, seed=42)


def test_each_cell_gets_its_quota_from_the_right_stratum():
    cells = [Cell("easy", "a/a", 2), Cell("hard", "b/b", 1)]
    picked = stratified_draw(POOL, cells, seed=1)
    by_id = {r["instance_id"]: r for r in POOL}
    assert len(picked) == 3
    assert [(by_id[i]["difficulty"], by_id[i]["repo"]) for i in picked] == [
        ("easy", "a/a"),
        ("easy", "a/a"),
        ("hard", "b/b"),
    ]


def test_excluded_ids_are_never_drawn():
    cells = [Cell("easy", "a/a", 2)]
    picked = stratified_draw(POOL, cells, seed=3, exclude={"a__a-1"})
    assert "a__a-1" not in picked


def test_cell_with_too_few_candidates_fails_loudly():
    with pytest.raises(ValueError, match="only 1"):
        stratified_draw(POOL, [Cell("easy", "b/b", 2)], seed=0)
