"""Tests: (1) the engine reproduces every number printed in the report;
(2) the additional checks behave as documented in the README."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "calc"))
from service_calc import Model  # noqa: E402

M = Model()
CIRCUITS = [(d.key, c) for d in M.designs.values() for c in d.circuits]


@pytest.mark.parametrize("key,c", CIRCUITS, ids=[f"{k}:{c.id}" for k, c in CIRCUITS])
def test_circuit_matches_report(key, c):
    assert c.watts == c.report["watts"]
    assert M.i_calc(c) == pytest.approx(c.report["i_calc"], abs=0.02)
    assert M.i_design(c) == pytest.approx(c.report["i_design"], abs=0.02)


@pytest.mark.parametrize("d", list(M.designs.values()), ids=list(M.designs))
def test_design_totals_match_report(d):
    t = M.totals(d)
    assert t["watts"] == d.report["watts"]
    # the report sums rounded circuit currents for I_calc (e.g. 16.53 vs exact 16.51)
    assert t["i_calc"] == pytest.approx(d.report["i_calc"], abs=0.03)
    assert t["i_design"] == pytest.approx(d.report["i_design"], abs=0.02)


@pytest.mark.parametrize("d", list(M.designs.values()), ids=list(M.designs))
def test_every_mcb_is_at_least_the_design_current(d):
    """The report's own selection rule: MCB rating >= design current."""
    assert all(r["ib_le_in"] for r in M.coordination_table(d))


@pytest.mark.parametrize("d", list(M.designs.values()), ids=list(M.designs))
def test_branch_circuits_are_coordinated(d):
    rows = [r for r in M.coordination_table(d) if r["circuit"] != "Main"]
    assert all(r["in_le_iz"] for r in rows)


@pytest.mark.parametrize("key", ["base", "approach1", "approach2"])
def test_main_mcb_exceeds_stated_cable_ampacity(key):
    """Finding F1: 32/40 A main MCB on a 4 mm2 cable the report rates at 30 A."""
    main = [r for r in M.coordination_table(M.designs[key]) if r["circuit"] == "Main"][0]
    assert main["i_z"] == 30 and main["i_n"] > main["i_z"] and not main["in_le_iz"]


def test_approach1_maximum_demand_matches_report():
    md = M.max_demand_w(M.designs["approach1"])
    assert md["total_w"] == pytest.approx(4138)
    assert md["current_a"] == pytest.approx(17.99, abs=0.01)


def test_like_for_like_maximum_demand_ordering():
    md = {k: M.max_demand_w(d)["total_w"] for k, d in M.designs.items()}
    assert md["base"] == pytest.approx(3223)
    assert md["approach2"] == pytest.approx(3646)
    assert md["base"] < md["approach2"] < md["approach1"]


def test_lumped_pf_is_more_conservative_than_per_load_for_approach1_ckt2():
    c = [c for c in M.designs["approach1"].circuits if c.id == "CKT-2"][0]
    assert M.i_calc(c) == pytest.approx(12.68, abs=0.01)
    assert M.i_calc_per_load(c) == pytest.approx(11.52, abs=0.01)
    assert M.i_calc(c) > M.i_calc_per_load(c)


def test_max_run_for_voltage_drop():
    c = [c for c in M.designs["approach1"].circuits if c.id == "CKT-2"][0]
    assert M.max_run_m(M.i_design(c), 2.5, 3) == pytest.approx(25.6, abs=0.2)
    assert M.max_run_m(M.i_design(c), 2.5, 5) == pytest.approx(25.6 * 5 / 3, abs=0.4)
    # doubling current halves the allowable run
    assert M.max_run_m(20, 2.5, 3) == pytest.approx(2 * M.max_run_m(40, 2.5, 3))


def test_room_geometry_is_consistent():
    w = (26 * 12 + 10) * 0.0254
    d = (15 * 12 + 6) * 0.0254
    assert w == pytest.approx(M.room["width_m"], abs=0.01)
    assert d == pytest.approx(M.room["depth_m"], abs=0.01)
    assert w * d == pytest.approx(M.room["area_m2"], abs=0.1)


def test_lumen_method_required_flux():
    phi = M.required_lumens_per_luminaire(300, 38.6, 12, 0.5, 0.8)
    assert phi == pytest.approx(2412.5, abs=1)


def test_lighting_power_density_approach1():
    s = M.lighting_summary(M.designs["approach1"])
    assert s["tubes"] == 12 and s["watts"] == 288
    assert s["lpd_w_per_m2"] == pytest.approx(7.46, abs=0.01)
