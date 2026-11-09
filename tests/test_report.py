from track3.report import pass_at_1, pass_at_k, sign_test


def test_pass_at_1_is_the_mean_over_runs():
    table = {"a": [True, False, True], "b": [False, False, False]}
    assert pass_at_1(table) == 2 / 6


def test_pass_at_k_counts_tasks_solved_by_any_seed():
    table = {"a": [True, False, False], "b": [False, False, False], "c": [True, True, True]}
    assert pass_at_k(table) == 2 / 3


def test_sign_test_two_sided_exact():
    # 1 win, 4 losses: 2 * P(X <= 1 | n=5, p=.5) = 2 * 6/32
    assert round(sign_test(1, 4), 4) == 0.375
    assert sign_test(0, 0) == 1.0
    assert sign_test(5, 0) == sign_test(0, 5)
