"""Executable golden cases and mathematical invariants, no database access."""
import itertools
import json
from pathlib import Path
from . import reference as ref


def run_checks():
    cases = json.loads(Path(__file__).with_name("golden_cases.json").read_text())
    for case in cases:
        d = ref.scale(case["answers"],case.get("reverse_indices",()))
        assert d["scored"] == case["scored"], case["name"]
        assert d["numerator"] == case["sum"], case["name"]
        assert d["denominator"] == case["denominator"], case["name"]
        assert d["score"] == case["score"], case["name"]
        assert ref.percentile(case["distribution"],d["score"]) == case["percentile"], case["name"]
    # Unequal item counts: equal scale weights, not pooled item weights.
    assert ref.spectrum([ref.scale([1,1]),ref.scale([4]*6)])["score"] == 2.5
    # Invalid scale excluded, while its items still contribute to missing rate.
    s = ref.spectrum([ref.scale(["5",1,1,1]),ref.scale([4]*4)])
    assert s["score"] == 4 and s["missing_percentage"] == 12.5
    assert ref.scale([1]*7501+[None]*2499)["is_valid"]
    assert not ref.scale([1]*7500+[None]*2500)["is_valid"]
    assert not ref.scale([1]*7499+[None]*2501)["is_valid"]
    for n in range(1,21):
        for missing in range(n+1):
            assert ref.scale([1]*(n-missing)+["5"]*missing)["is_valid"] == (4*missing<n)
    for values in itertools.product(range(1,5),repeat=4):
        score = ref.scale(values)["score"]
        assert 1<=score<=4
        if values[0]<4:
            higher = (values[0]+1,)+values[1:]
            assert ref.scale(higher)["score"] >= score
            assert ref.scale(higher,[0])["score"] <= ref.scale(values,[0])["score"]
    d = [1,1,1,2,3,4]
    ps = [ref.percentile(d,x/100) for x in range(0,501)]
    assert ps==sorted(ps)
    assert ref.percentile(d,2)==ref.percentile(list(reversed(d)),2)
    assert ref.percentile([1]+[4]*99,1)==1
    assert ref.percentile([1]*99+[4],1)==99
    assert ref.percentile([1]+[4]*7,1)==12  # 12.5 -> even integer.
    assert ref.percentile([1]*3+[4]*5,1)==38  # 37.5 -> even integer.
    key = [dict(item_code="a",scale="s",spectrum="t"),
           dict(item_code="catch",scale="s",spectrum="t",is_attention_check=True)]
    assert ref.scores({"a":"2","catch":"1"},key)==ref.scores({"a":"2","catch":"4"},key)
    return dict(golden_cases=len(cases),invariants="PASS")
