"""Small made-up schedule: day selection, repairs, stop buffers and route directions."""
import os
import zipfile
from datetime import datetime

import numpy as np
import pandas as pd
import pytest

from dtaccess import Settings
from dtaccess import gtfs as G

RUN = datetime(2026, 3, 3, 8, 0)   # a Tuesday


def _write(tmp, tables):
    z = os.path.join(tmp, "feed.zip")
    with zipfile.ZipFile(z, "w") as zf:
        for name, rows in tables.items():
            zf.writestr(name + ".txt", pd.DataFrame(rows[1:], columns=rows[0]).to_csv(index=False))
        zf.writestr("LICENSE.txt", "not a GTFS table")
    return z


@pytest.fixture()
def feed(tmp_path):
    t = {
        "agency": [["agency_id", "agency_name", "agency_url", "agency_timezone"], ["X", "City Bus", "-", "America/Phoenix"], ["Y", "City Rail", "https://rail.example", "America/Phoenix"]],
        "stops": [["stop_id", "stop_lat", "stop_lon"], ["A", 0.0, 0.0], ["B", 0.0, 0.01], ["C", 0.0, 0.02], ["D", 0.01, 0.0]],
        "routes": [["route_id", "agency_id", "route_type"], ["r1", "X", "3"], ["r2", "Y", "2"], ["r3", "X", "3"], ["r4", "X", "1501"]],
        "calendar": [["service_id", "monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday", "start_date", "end_date"],
                     ["wk", 1, 1, 1, 1, 1, 0, 0, "20260101", "20261231"], ["old", 1, 1, 1, 1, 1, 0, 0, "20190101", "20191231"]],
        "trips": [["route_id", "service_id", "trip_id", "direction_id"], ["r1", "wk", "t1", "0"], ["r1", "wk", "t1twin", "0"], ["r2", "wk", "t2", "0"],
                  ["r3", "wk", "t3", "0"], ["r1", "old", "t_old", "0"], ["r1", "wk", "t_bad", "0"], ["r4", "wk", "t_freq", "0"]],
        "stop_times": [["trip_id", "arrival_time", "departure_time", "stop_id", "stop_sequence"],
                       ["t1", "08:10:00", "08:10:00", "A", 1], ["t1", "08:15:00", "08:15:00", "B", 2], ["t1", "08:20:00", "08:20:00", "C", 3],
                       ["t1twin", "08:10:00", "08:10:00", "A", 1], ["t1twin", "08:15:00", "08:15:00", "B", 2], ["t1twin", "08:20:00", "08:20:00", "C", 3],
                       ["t2", "08:20:00", "08:20:00", "A", 1], ["t2", "08:30:00", "08:30:00", "D", 2],
                       ["t3", "10:00:00", "10:00:00", "D", 1], ["t3", "10:10:00", "10:10:00", "A", 2],
                       ["t_old", "08:00:00", "08:00:00", "A", 1], ["t_old", "08:05:00", "08:05:00", "B", 2],
                       ["t_bad", "80:00:00", "80:00:00", "A", 1], ["t_bad", "80:05:00", "80:05:00", "B", 2],
                       ["t_freq", "00:01:00", "00:01:00", "C", 1], ["t_freq", "00:06:00", "00:06:00", "B", 2]],
        "frequencies": [["trip_id", "start_time", "end_time", "headway_secs"], ["t_freq", "08:30:00", "08:30:00", "0"]],
    }
    return _write(str(tmp_path), t), str(tmp_path)


def _load(feed):
    z, tmp = feed
    return G.load_feeds([z], RUN, os.path.join(tmp, "work"), "test", Settings(), log=lambda *a: None)


def test_day_selection_and_repairs(feed):
    g = _load(feed)
    assert set(g["trips"].trip_id) == {"t1", "t2", "t3", "t_freq"}          # old service, the twin and the 80-hour trip are gone
    n = g["notes"]
    assert n["exact_twins_dropped"] == 1 and n["trips_time_ge72h_dropped_0"] == 1
    assert n["frequency_headway_lt1_0"] == {"rows": 1, "single_departures": 1}
    st = g["stop_times"]; assert list(st[st.trip_id == "t_freq"].departure_time) == ["08:30:00", "08:35:00"]   # one departure at start_time
    with zipfile.ZipFile(g["zips"][0]) as zf:
        names = set(zf.namelist())
        assert "LICENSE.txt" not in names and "frequencies.txt" not in names          # empty table not written
        ag = pd.read_csv(zf.open("agency.txt")); rt = pd.read_csv(zf.open("routes.txt"), dtype=str)
    assert ag.set_index("agency_id").agency_url["X"] == "http://unknown.invalid"      # "-" is not a URL
    assert rt.set_index("route_id").route_type["r4"] == "3"                            # 1501 is remapped for routing only
    assert g["routes"].set_index("route_id").route_type["r4"] == "1501"                # analysis tables keep the feed's code


def test_stop_buffers(feed):
    g = _load(feed)
    un, counts = G.un_rule_buffers(g)
    b = un.set_index("stop_id").buf
    assert (b["A"], b["B"], b["C"], b["D"]) == (1000, 500, 500, 1000)      # A and D are served by rail
    assert counts["rail_metro_ferry_cable"] == 1
    ag = G.agency_rule_buffers(g).groupby("stop_id").buf.max()
    assert (ag["A"], ag["B"], ag["D"]) == (1000, 500, 1000)


def test_un_rule_marked_rapid_bus(feed):
    g = _load(feed)
    un, counts = G.un_rule_buffers(g, un_brt={"agency_name": ["City Bus"]})
    assert counts["brt_marked"] == 3 and set(un.buf) == {1000}


def test_route_presence_directions(feed):
    g = _load(feed)
    cell = lambda lat, lon: np.array([{(0.0, 0.0): "cA", (0.0, 0.01): "cB", (0.0, 0.02): "cC", (0.01, 0.0): "cD"}.get((round(a, 2), round(b, 2))) for a, b in zip(lat, lon)], dtype=object)
    p = G.route_presence(g, cell, Settings()).set_index(["uid", "sector"]).n_route_dirs
    assert p[("cA", 2)] == 1      # the bus leaves A eastwards
    assert p[("cA", 0)] == 1      # the train leaves A northwards
    assert p[("cB", 2)] == 1
    assert p[("cC", 6)] == 1      # the single 08:30 departure runs C -> B, westwards
    assert ("cD", 4) not in p.index   # the 10:00 trip is outside 08:00-08:59


def test_repairs_can_be_switched_off(feed):
    z, tmp = feed
    S = Settings(); S.repairs.drop_exact_twin_trips = False
    g = G.load_feeds([z], RUN, os.path.join(tmp, "work2"), "test", S, log=lambda *a: None)
    assert "t1twin" in set(g["trips"].trip_id)
