"""Deficit Round Robin: share a limited number of slots fairly between tenants.

Picture a ring of tenants that have queued jobs. We walk around the ring. When we ARRIVE at a tenant
we give it `weight` credits (its "deficit"); it may take one slot per credit. A tenant with weight 3
therefore gets 3 slots for every 1 slot of a weight-1 tenant, no matter how long its queue is.
If the slots run out in the middle of a visit, the pointer STAYS on that tenant, with its leftover
credits, so the next call carries on (otherwise the first tenant on the ring would win every time).
All jobs cost 1 credit here; a tenant with 1,000,000 queued jobs still only gets its share.
"""


class DRR:
    def __init__(self):
        self.ring: list[str] = []        # tenants with queued jobs, in visiting order
        self.pos = 0                     # whose turn it is
        self.deficit: dict[str, int] = {}
        self.fresh = True                # True = we just arrived at ring[pos] and it has not been topped up yet

    def allocate(self, queued: dict[str, int], weights: dict[str, int], capacity: int) -> dict[str, int]:
        """queued = jobs waiting per tenant. Returns how many jobs to take from each tenant (sum <= capacity)."""
        take = {t: 0 for t in queued}
        self.ring = [t for t in self.ring if queued.get(t, 0) > 0] + \
                    [t for t in queued if queued[t] > 0 and t not in self.ring]
        self.pos %= max(len(self.ring), 1)
        while capacity > 0 and self.ring:
            t = self.ring[self.pos]
            if self.fresh:
                self.deficit[t] = self.deficit.get(t, 0) + max(1, weights.get(t, 1))
            n = min(self.deficit[t], queued[t] - take[t], capacity)
            take[t] += n
            self.deficit[t] -= n
            capacity -= n
            if take[t] >= queued[t]:                       # this tenant's queue is empty: leave the ring
                self.deficit[t] = 0
                self.ring.pop(self.pos)
                self.pos %= max(len(self.ring), 1)
                self.fresh = True
            elif self.deficit[t] == 0:                     # used all its credits: next tenant
                self.pos = (self.pos + 1) % len(self.ring)
                self.fresh = True
            else:                                          # ran out of slots mid-visit: stay here next time
                self.fresh = False
        return take
