import pytest

from jobbot.config import load_profile
from jobbot.screening import Answerer


@pytest.fixture
def a():
    return Answerer(load_profile())


@pytest.mark.parametrize("q,opts,expected", [
    ("Do you have a valid CPC certification?", ["Yes", "No"], "Yes"),
    ("Are you currently living in Dubai?", ["Yes", "No"], "Yes"),
    ("Do you have a Bachelor's degree?", ["Yes", "No"], "Yes"),
    ("Do you speak Arabic?", ["Yes", "No"], "No"),
    ("Email", None, "test@example.invalid"),
])
def test_verified_answers(a, q, opts, expected):
    r = a.answer(q, opts)
    assert r.ok and r.answer == expected


@pytest.mark.parametrize("q,opts", [
    ("Are you legally authorized to work in the UAE?", ["Yes", "No"]),
    ("Will you require visa sponsorship?", ["Yes", "No"]),
    ("What is your expected monthly salary (AED)?", None),
    ("I declare that the information provided is true", None),
    ("I agree to the terms and conditions", None),
    ("Please enter your passport number", None),
    ("What is your date of birth?", None),
    ("How many years of medical coding experience do you have?", None),
    ("Do you have a bachelor's degree in Nursing?", ["Yes", "No"]),
    ("Do you have a DHA coding licence?", ["Yes", "No"]),
    ("What is your favourite colour?", None),
])
def test_stops(a, q, opts):
    r = a.answer(q, opts)
    assert not r.ok and r.answer is None
