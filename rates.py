"""Driver pay rates: a per-driver base rate plus per-route overrides.

Shared by the bot and by report.py so both compute pay the same way.
"""

from config import DEFAULT_DRIVER_RATE
from data import get_driver_rate, get_route_rates


class RateCard:
    """A driver's pay rates: a base rate plus per-route overrides."""

    def __init__(self, base, overrides):
        self.base = base
        self.overrides = overrides

    def for_route(self, route):
        return self.overrides.get(route, self.base)

    def pay(self, routes):
        """routes: { route: count } -> driver pay for that day."""
        return sum(count * self.for_route(route) for route, count in routes.items())

    def suffix(self, route):
        """Per-route rate tag, shown only when the driver has overrides."""
        return f" @ ${self.for_route(route):.2f}" if self.overrides else ""

    def label(self):
        if not self.overrides:
            return f"${self.base:.2f}/pkg"
        parts = [f"${self.base:.2f} base"]
        parts += [f"R{route} ${rate:.2f}" for route, rate in sorted(self.overrides.items())]
        return " · ".join(parts)


def get_rate_card(user_id) -> RateCard:
    return RateCard(get_driver_rate(user_id, DEFAULT_DRIVER_RATE), get_route_rates(user_id))
