"""Electrical-service calculation engine for the LASSET Lab (Room 12B-16L) designs.

Re-derives every figure in the EEE384 Group 02 report from first principles
(I = P / (V x PF), I_design = 1.2 x I_calc) and adds checks the report does not
contain: overload-protection coordination (I_b <= I_n <= I_z), maximum
cable run for a voltage-drop limit, a like-for-like maximum-demand comparison
of the three designs, and a lumen-method sensitivity check of the lighting claim.

All inputs live in ``data/designs.json``; nothing is hard-coded here.
"""
from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional

DATA = Path(__file__).resolve().parents[1] / "data" / "designs.json"
COPPER_TEMP_COEFF = 0.00393      # per kelvin, copper
HOT_FACTOR = 1 + COPPER_TEMP_COEFF * (70 - 20)   # conductor at 70 C -> ~1.196


@dataclass(frozen=True)
class Load:
    name: str
    qty: int
    watts: float
    pf: float
    cat: str

    @property
    def total_w(self) -> float:
        return self.qty * self.watts


@dataclass
class Circuit:
    id: str
    name: str
    cable_mm2: float
    mcb_a: float
    loads: List[Load]
    lumped_pf: Optional[float]
    report: dict

    @property
    def watts(self) -> float:
        return sum(l.total_w for l in self.loads)


@dataclass
class Design:
    key: str
    title: str
    file: str
    main_mcb_a: float
    main_cable_mm2: float
    circuits: List[Circuit]
    report: dict


class Model:
    def __init__(self, path: Path = DATA):
        raw = json.loads(Path(path).read_text())
        self.v = raw["supply"]["voltage_v"]
        self.margin = raw["design_margin"]
        self.room = raw["room"]
        self.demand_factors = {k: v for k, v in raw["demand_factors"].items() if not k.startswith("_")}
        self.ampacity = {float(k): v for k, v in raw["cable_ampacity_a"].items() if not k.startswith("_")}
        self.r20 = {float(k): v for k, v in raw["cable_resistance_ohm_per_km_20c"].items() if not k.startswith("_")}
        self.designs: Dict[str, Design] = {}
        for key, d in raw["designs"].items():
            circuits = [
                Circuit(c["id"], c["name"], c["cable_mm2"], c["mcb_a"],
                        [Load(**l) for l in c["loads"]], c.get("lumped_pf"), c["report"])
                for c in d["circuits"]
            ]
            self.designs[key] = Design(key, d["title"], d["file"], d["main_mcb_a"],
                                       d["main_cable_mm2"], circuits, d["report"])

    # ---------------------------------------------------------------- currents
    def load_current(self, l: Load) -> float:
        return l.total_w / (self.v * l.pf)

    def i_calc(self, c: Circuit) -> float:
        """Report method: per-load PF, except where the report lumps the circuit at one PF."""
        if c.lumped_pf:
            return c.watts / (self.v * c.lumped_pf)
        return sum(self.load_current(l) for l in c.loads)

    def i_calc_per_load(self, c: Circuit) -> float:
        return sum(self.load_current(l) for l in c.loads)

    def i_design(self, c: Circuit) -> float:
        return self.margin * self.i_calc(c)

    def totals(self, d: Design) -> dict:
        i_calc = sum(self.i_calc(c) for c in d.circuits)
        return {"watts": sum(c.watts for c in d.circuits), "i_calc": i_calc,
                "i_design": self.margin * i_calc}

    # ------------------------------------------------------------ protection
    def coordination(self, i_b: float, i_n: float, cable_mm2: float) -> dict:
        i_z = self.ampacity[cable_mm2]
        return {"i_b": i_b, "i_n": i_n, "i_z": i_z,
                "ib_le_in": i_b <= i_n + 1e-9, "in_le_iz": i_n <= i_z + 1e-9,
                "loading_pct": 100 * i_b / i_n}

    def coordination_table(self, d: Design) -> List[dict]:
        rows = []
        for c in d.circuits:
            r = self.coordination(self.i_design(c), c.mcb_a, c.cable_mm2)
            r["circuit"] = c.id
            rows.append(r)
        r = self.coordination(self.totals(d)["i_design"], d.main_mcb_a, d.main_cable_mm2)
        r["circuit"] = "Main"
        rows.append(r)
        return rows

    # --------------------------------------------------------------- demand
    def max_demand_w(self, d: Design) -> dict:
        """Apply the report's demand factors per load category (Approach 1 convention)."""
        by_cat: Dict[str, float] = {}
        for c in d.circuits:
            for l in c.loads:
                by_cat[l.cat] = by_cat.get(l.cat, 0.0) + l.total_w
        demand = {k: by_cat[k] * self.demand_factors[k] for k in by_cat}
        total = sum(demand.values())
        return {"connected_by_cat": by_cat, "demand_by_cat": demand, "total_w": total,
                "current_a": total / self.v}

    # -------------------------------------------------------- voltage drop
    def r_hot(self, mm2: float) -> float:
        """Ohm/km at 70 C conductor temperature."""
        return self.r20[mm2] * HOT_FACTOR

    def max_run_m(self, i_a: float, cable_mm2: float, limit_pct: float) -> float:
        """Longest one-way run (m) keeping 1-phase voltage drop <= limit_pct at current i_a.

        dV = 2 * I * R' * L  (resistive; reactance neglected for small LV conductors).
        """
        allowed_v = limit_pct / 100 * self.v
        return allowed_v / (2 * i_a * self.r_hot(cable_mm2) / 1000)

    # ------------------------------------------------------------- lighting
    @staticmethod
    def required_lumens_per_luminaire(target_lux: float, area_m2: float, n: int,
                                      utilisation: float, maintenance: float) -> float:
        """Lumen method: E = N * phi * UF * MF / A  ->  phi = E * A / (N * UF * MF)."""
        return target_lux * area_m2 / (n * utilisation * maintenance)

    def lighting_summary(self, d: Design) -> dict:
        tubes = sum(l.qty for c in d.circuits for l in c.loads if l.cat == "lighting" and "tube" in l.name.lower())
        watts = sum(l.total_w for c in d.circuits for l in c.loads if l.cat == "lighting" and "tube" in l.name.lower())
        area = self.room["area_m2"]
        return {"tubes": tubes, "watts": watts, "lpd_w_per_m2": watts / area, "area_m2": area}

    # ---------------------------------------------------------------- misc
    def room_diagonal_m(self) -> float:
        return math.hypot(self.room["width_m"], self.room["depth_m"])
