"""All fixed settings of the method in one place. The defaults are the published ones."""
from dataclasses import dataclass, field, asdict


@dataclass
class Repairs:
    """Feed repairs. Each one fixes a feed that the routing engine (R5 7.5.1) would otherwise reject,
    or removes records that cannot run on the chosen day. All are on by default, as in the published runs."""
    drop_exact_twin_trips: bool = True          # same route, direction, stops and times listed twice
    drop_trips_ge_72h: bool = True              # a stop time of 72 h or more is malformed
    flex_empty_times: bool = True               # demand-responsive feeds without arrival/departure times
    fill_blank_agency_id: bool = True           # one-agency feed with blank agency_id on routes
    zero_window_frequency_as_one_departure: bool = True   # frequency row with headway < 1 s and start = end
    fill_stop_name: bool = True                 # missing stop_name -> stop_id (names are not used)
    drop_duplicate_agency_id: bool = True
    drop_duplicate_frequency_rows: bool = True
    fill_agency_timezone: bool = True           # from the feed itself, else from --timezone
    placeholder_agency_url: bool = True         # missing or unparseable agency_url
    remap_unknown_route_types: bool = True      # codes above 1500 or unknown basic codes -> 3 (bus), routing copy only
    drop_empty_tables: bool = True
    # only used with feed_copy="original" (route on the publisher's zip)
    drop_duplicate_keys_and_orphans: bool = True
    drop_feed_info_missing_required: bool = True
    skip_feeds_without_active_trips: bool = True


@dataclass
class Settings:
    res: int = 8                    # H3 resolution
    threshold_min: float = 30.0     # reach threshold, minutes
    n_sectors: int = 8              # compass sectors; sector k covers [45k, 45k+45) degrees clockwise from north
    min_car: int = 5                # a direction counts if a car reaches at least this many cells
    peak_start_hour: int = 8        # departures 08:00-08:59
    window_min: int = 60
    max_transit_min: int = 150      # routing cap, transit
    max_car_min: int = 60           # routing cap, car (only times up to the threshold are used)
    min_pop_origin: float = 100.0   # a cell is an origin if it has at least this many residents
    buf_bus_m: int = 500            # stop buffer, bus and tram
    buf_rail_m: int = 1000          # stop buffer, rail, metro, ferry, cable car, marked rapid bus
    osm_buffer_m: int = 10000       # street network clip: boundary plus this margin
    batch: int = 600                # origins per routing batch (memory only; results do not depend on it)
    heap: str = "30G"               # Java heap for R5
    walk_matrix: bool = False       # also route walk-only (diagnostic; enters no indicator)
    boot: int = 1000                # bootstrap resamples for the direction-share interval
    seed: int = 103
    repairs: Repairs = field(default_factory=Repairs)

    @property
    def sector_deg(self) -> float:
        return 360.0 / self.n_sectors

    def as_dict(self) -> dict:
        return asdict(self)
