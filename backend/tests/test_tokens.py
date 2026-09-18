from app.llm.tokens import CHARS_PER_TOKEN, estimate_tokens
from app.llm.types import Message


def test_estimate_grows_with_the_text():
    short = estimate_tokens([Message("user", "a" * 100)])
    long = estimate_tokens([Message("user", "a" * 1000)])
    assert long > short


def test_estimate_sums_every_message():
    one = estimate_tokens([Message("user", "a" * 300)])
    two = estimate_tokens([Message("system", "a" * 300), Message("user", "a" * 300)])
    assert two > one


def test_estimate_stays_above_a_real_tokenizer():
    # Un tokeniseur réel sort du français autour de quatre caractères par
    # jeton. L'estimation doit rester au-dessus : elle sert à décider d'une
    # bascule, et se tromper vers le bas coupe une rédaction au milieu.
    text = "Le dispositif retenu couvre le périmètre décrit au cadrage. " * 20
    assert estimate_tokens([Message("user", text)]) > len(text) / 4
    assert CHARS_PER_TOKEN < 4


def test_empty_messages_cost_nothing_absurd():
    assert 0 < estimate_tokens([Message("user", "")]) < 5
