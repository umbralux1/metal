from decimal import Decimal as D

import pytest

from app.catalog.calculator import CalcError, CalcInput, calculate, parse_input
from app.catalog.models import Price, Product, Unit

CUT = 5000  # 50 ₽ за рез
TON_FROM = 1000


@pytest.fixture
def rebar() -> Product:
    """Арматура 12 мм: пруток 11,7 м, 0,888 кг/м, 43,25 ₽/м, 48 700 ₽/т."""
    return Product(
        name="Арматура 12 мм",
        length_m=D("11.7"),
        weight_per_m_kg=D("0.888"),
        base_unit=Unit.METER,
        prices=[Price(unit=Unit.METER, amount_kop=4325), Price(unit=Unit.TON, amount_kop=4870000)],
    )


def calc(product, **kw):
    return calculate(product, CalcInput(**kw), CUT, TON_FROM)


def test_one_bar(rebar):
    r = calc(rebar, unit="pcs", quantity=D(1))
    assert (r.pieces, r.meters, r.weight_kg) == (1, D("11.7"), D("10.39"))
    assert r.material_kop == 50603  # 11,7 × 43,25 = 506,025 → 506,03 ₽
    assert r.total_kop == 50603


def test_meters_round_up_to_whole_bars(rebar):
    r = calc(rebar, unit="m", quantity=D(30))
    assert r.pieces == 3 and r.meters == D("35.1")
    assert any("Округлили" in n for n in r.notes)


def test_exact_meters_have_no_rounding_note(rebar):
    r = calc(rebar, unit="m", quantity=D("23.4"))
    assert r.pieces == 2 and not r.notes


def test_kilograms(rebar):
    r = calc(rebar, unit="kg", quantity=D(100))  # 100 / 0,888 = 112,6 м → 10 прутков
    assert r.pieces == 10 and r.meters == D("117.0")


def test_ton_price_from_one_ton(rebar):
    r = calc(rebar, unit="pcs", quantity=D(100))  # 1170 м = 1038,96 кг
    assert r.price_unit == Unit.TON
    assert r.material_kop == round(D("1038.96") / 1000 * 4870000)


def test_cutting_exact_fit_saves_last_cut(rebar):
    # 11,7 = 3 × 3,9: из каждого прутка 3 отрезка за 2 реза
    r = calc(rebar, cut=True, cut_length_m=D("3.9"), cut_count=10)
    assert r.pieces == 4
    assert r.cuts == 7  # 3 полных прутка × 2 + 1 рез на четвёртом
    assert r.cut_kop == 7 * CUT
    assert r.waste_m == D("7.8")
    assert r.total_kop == r.material_kop + r.cut_kop


def test_cutting_with_remainder(rebar):
    # 2,5 м: 4 отрезка из прутка, остаток 1,7 м
    r = calc(rebar, cut=True, cut_length_m=D("2.5"), cut_count=9)
    assert (r.pieces, r.cuts, r.waste_m) == (3, 9, D("12.6"))


@pytest.mark.parametrize(
    ("kw", "message"),
    [
        ({"unit": "pcs", "quantity": D(0)}, "больше нуля"),
        ({"unit": "pcs", "quantity": D("1.5")}, "целое"),
        ({"unit": "pcs", "quantity": None}, "больше нуля"),
        ({"cut": True, "cut_length_m": D(15), "cut_count": 2}, "длиннее прутка"),
        ({"cut": True, "cut_length_m": D(3), "cut_count": None}, "количество отрезков"),
    ],
)
def test_input_errors(rebar, kw, message):
    with pytest.raises(CalcError, match=message):
        calc(rebar, **kw)


def test_parse_input_accepts_comma(rebar):
    inp = parse_input({"cut": "1", "cut_len": "3,9", "cut_count": "10"}, rebar)
    assert inp.cut and inp.cut_length_m == D("3.9") and inp.cut_count == 10


def test_parse_input_rejects_garbage(rebar):
    with pytest.raises(CalcError, match="введите число"):
        parse_input({"unit": "m", "qty": "много"}, rebar)


def test_no_price():
    product = Product(name="Без цены", length_m=D(6), weight_per_m_kg=D(1), base_unit=Unit.METER, prices=[])
    with pytest.raises(CalcError, match="по запросу"):
        calc(product, unit="pcs", quantity=D(1))
