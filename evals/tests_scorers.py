from nova_evals.scorers import bullet_count, max_words, must_include, numeric, regex, score, script


def test_basic_scorers() -> None:
    assert must_include("The capital is Canberra.", ["canberra"])[0]
    assert numeric("It is 442,257,849.", 442257849)[0]
    assert not numeric("about 12", 13)[0]
    assert regex("  YES ", r"^\s*YES\.?\s*$")[0]
    assert max_words("one two three", 3)[0] and not max_words("a b c d", 3)[0]
    assert bullet_count("- a\n- b\n- c", 3)[0]
    assert script("भारत की राजधानी नई दिल्ली है।", "devanagari")[0]


def test_score_tool_and_combined() -> None:
    parts = [{"type": "tool_call", "tool_name": "calculator"}, {"type": "text", "text": "= 42"}]
    out = score({"tool": "calculator", "numeric": 42, "reference_answer": "ignored"}, "= 42", parts)
    assert [n for n, _, _ in out] == ["tool", "numeric"] and all(ok for _, ok, _ in out)
