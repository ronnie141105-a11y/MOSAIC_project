"""Shared study rules for a bounded taxi queue and protected takeoff release."""
MAX_ACTIVE_DEPARTURES = 4
MINIMUM_TAKEOFF_GAP_S = 120
ARRIVAL_PROTECTION_NM = 6
# Predicted touchdown must follow departure wheel-off by at least this margin.
ARRIVAL_PROTECTION_S = 30
# A ready queue leader may line up while waiting for its protected takeoff slot.
LINEUP_LOOKAHEAD_S = None
LANDING_RELEASE_FRACTION = 1.0


def arrival_blocks_departure(roll_start,takeoff,approach_gate,touchdown,runway_exit):
    """Six NM is a roll-start cutoff; wheel-off precedes touchdown separately.

    Bitwise boolean operators also support the optimizer's NumPy pair arrays.
    """
    return (((roll_start>=approach_gate)&(roll_start<runway_exit))
        |((roll_start<touchdown)&(takeoff+ARRIVAL_PROTECTION_S>=touchdown)))
