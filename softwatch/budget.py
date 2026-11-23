"""Per-run request budgets. A stage that runs out of budget stops; it never borrows from another."""


class BudgetExceeded(RuntimeError):
    pass


class Budget:
    def __init__(self, limits):
        self.limits = {
            "github_rest": limits["github_rest_per_run"],
            "github_graphql": limits["github_graphql_per_run"],
            "hn": limits["hn_per_run"],
        }
        self.used = {k: 0 for k in self.limits}

    def spend(self, key, n=1):
        if self.used[key] + n > self.limits[key]:
            raise BudgetExceeded(key)
        self.used[key] += n

    def remaining(self, key):
        return self.limits[key] - self.used[key]
