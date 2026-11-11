# SPDX-FileCopyrightText: 2026 Miki
# SPDX-License-Identifier: BSD-3-Clause

"""Named minimum (or maximum) cost flow methods: registry, solve, prepare."""

from abc import ABC, abstractmethod
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from types import MappingProxyType

from protee import __version__
from protee.flow._augmenting import cycle_canceling, successive_shortest_paths
from protee.flow._feasibility import Feasibility, check_feasibility
from protee.flow._normal import (
    Normal,
    UnboundedCheck,
    normalize,
    signed_costs,
    tolerance_for,
)
from protee.flow._problem import FlowProblem, Sense
from protee.flow._result import Certificate, FlowResult, Status
from protee.flow._simplex import NetworkSimplex, PivotRule

type Number = int | float


@dataclass(frozen=True, slots=True)
class MethodInfo:
    """Description of a flow method of the registry.

    Attributes
    ----------
    name : str
        The name to pass as ``method``.
    summary : str
    warm_start : bool
        Whether :meth:`Prepared.solve` reuses the previous solution after a
        change of costs.
    complexity : str
        Worst-case bound, with ``n`` nodes, ``m`` arcs, ``U`` the largest
        capacity and ``C`` the largest absolute cost.
    reference : str
    options : tuple of str
        Keyword options accepted by :func:`solve` and :func:`prepare`.
    """

    name: str
    summary: str
    warm_start: bool
    complexity: str
    reference: str
    options: tuple[str, ...]


class Prepared(ABC):
    """A flow problem prepared for one method, to be solved for many costs.

    The structure (graph, bounds, supplies) is fixed; :meth:`solve` takes
    new costs. Methods with ``warm_start`` resume from the previous
    solution; the others start again.
    """

    def __init__(self, problem: FlowProblem, method: MethodInfo) -> None:
        self.problem = problem
        self.method = method
        self._normal = normalize(problem)
        self._unbounded = UnboundedCheck(problem)
        self._feasibility: Feasibility | None = None

    def feasibility(self) -> Feasibility:
        """Feasibility of the prepared structure, computed once: it does not
        depend on the costs."""
        if self._feasibility is None:
            self._feasibility = check_feasibility(self.problem)
        return self._feasibility

    def solve(
        self, cost: Sequence[Number] | None = None, sense: Sense | None = None
    ) -> FlowResult:
        """Solve for ``cost`` (the prepared costs by default) and ``sense``.

        Returns
        -------
        FlowResult
            ``counters`` count the work of this call only.
        """
        problem = (
            self.problem
            if cost is None and sense is None
            else self.problem.with_cost(
                self.problem.cost if cost is None else cost, sense
            )
        )
        cycle = self._unbounded.cycle(signed_costs(problem))
        if cycle is not None:
            feasibility = self.feasibility()
            if feasibility.feasible:
                return self._result(problem, Status.UNBOUNDED, None, None, cycle, {})
            return self._result(
                problem, Status.INFEASIBLE, None, None, feasibility.cut, {}
            )
        counters: dict[str, int] = {}
        found = self._run(problem, counters)
        if found is None:
            cut = self.feasibility().cut
            return self._result(problem, Status.INFEASIBLE, None, None, cut, counters)
        y, potentials = found
        return self._result(
            problem, Status.OPTIMAL, self._normal.flow(y), potentials, None, counters
        )

    @abstractmethod
    def _run(
        self, problem: FlowProblem, counters: dict[str, int]
    ) -> tuple[list[int], list[Number]] | None:
        """Optimal standard-form flow and potentials, ``None`` if infeasible."""

    def _result(
        self,
        problem: FlowProblem,
        status: Status,
        flow: tuple[int, ...] | None,
        potentials: Sequence[Number] | None,
        certificate: Certificate | None,
        counters: dict[str, int],
    ) -> FlowResult:
        return FlowResult(
            status=status,
            method=self.method.name,
            objective=None if flow is None else problem.objective(flow),
            flow=flow,
            potentials=None if potentials is None else tuple(potentials),
            certificate=certificate,
            counters=MappingProxyType(dict(counters)),
            version=__version__,
        )


class _PreparedSimplex(Prepared):
    def __init__(
        self,
        problem: FlowProblem,
        method: MethodInfo,
        pivot_rule: PivotRule = "block_search",
    ) -> None:
        super().__init__(problem, method)
        self._simplex = NetworkSimplex(self._normal, pivot_rule)

    def _run(
        self, problem: FlowProblem, counters: dict[str, int]
    ) -> tuple[list[int], list[Number]] | None:
        simplex = self._simplex
        simplex.set_costs(signed_costs(problem))
        before = dict(simplex.counters)
        feasible = simplex.run()
        counters.update({k: simplex.counters[k] - before[k] for k in before})
        if not feasible:
            return None
        return simplex.solution()


class _PreparedCycleCanceling(Prepared):
    def _run(
        self, problem: FlowProblem, counters: dict[str, int]
    ) -> tuple[list[int], list[Number]] | None:
        feasibility = self.feasibility()
        if feasibility.flow is None:
            return None
        normal = self._with_cost(signed_costs(problem))
        y = [x - lo for x, lo in zip(feasibility.flow, normal.lower, strict=True)]
        counters.update(cycles_canceled=0, bellman_ford_runs=0)
        return y, cycle_canceling(normal, y, counters)

    def _with_cost(self, cost: list[Number]) -> Normal:
        return replace(self._normal, cost=cost, tolerance=tolerance_for(cost))


class _PreparedSuccessiveShortestPaths(_PreparedCycleCanceling):
    def _run(
        self, problem: FlowProblem, counters: dict[str, int]
    ) -> tuple[list[int], list[Number]] | None:
        counters.update(augmentations=0, dijkstra_runs=0)
        return successive_shortest_paths(
            self._with_cost(signed_costs(problem)), counters
        )


_FACTORIES: dict[str, Callable[..., Prepared]] = {
    "network_simplex": _PreparedSimplex,
    "cycle_canceling": _PreparedCycleCanceling,
    "successive_shortest_paths": _PreparedSuccessiveShortestPaths,
}

METHODS: Mapping[str, MethodInfo] = MappingProxyType(
    {
        "network_simplex": MethodInfo(
            "network_simplex",
            "Primal network simplex, strongly feasible trees (Cunningham), big-M start.",
            True,
            "finite (anti-cycling); pseudo-polynomial bounds in practice",
            "Ahuja, Magnanti, Orlin, Network Flows (1993), ch. 11; Cunningham (1976)",
            ("pivot_rule",),
        ),
        "cycle_canceling": MethodInfo(
            "cycle_canceling",
            "Feasible flow by maximum flow, then cancel negative residual cycles (Bellman-Ford).",
            False,
            "O(n m^2 C U)",
            "Klein (1967); Ahuja, Magnanti, Orlin (1993), section 9.6",
            (),
        ),
        "successive_shortest_paths": MethodInfo(
            "successive_shortest_paths",
            "Augment along shortest paths with node potentials (Dijkstra on reduced costs).",
            False,
            "O(n U (m + n log n)), U the total supply after saturation",
            "Edmonds, Karp (1972); Tomizawa (1971); Ahuja, Magnanti, Orlin (1993), section 9.7",
            (),
        ),
    }
)


def methods() -> tuple[MethodInfo, ...]:
    """The flow methods of the registry, in a fixed order."""
    return tuple(METHODS.values())


def prepare(problem: FlowProblem, *, method: str, **options: object) -> Prepared:
    """Prepare ``problem`` for a named method (see :func:`methods`).

    Parameters
    ----------
    problem : FlowProblem
    method : str
        A name from :func:`methods`; there is no default: the choice of the
        method stays the caller's.
    **options
        Options of the method, such as ``pivot_rule`` (``"block_search"``
        or ``"dantzig"``) for ``network_simplex``.

    Returns
    -------
    Prepared

    Raises
    ------
    ValueError
        If the method is unknown.
    TypeError
        If an option does not belong to the method.
    """
    if method not in METHODS:
        raise ValueError(
            f"unknown flow method {method!r}; choose among {sorted(METHODS)}"
        )
    info = METHODS[method]
    unknown = set(options) - set(info.options)
    if unknown:
        raise TypeError(f"method {method!r} takes no option {sorted(unknown)}")
    return _FACTORIES[method](problem, info, **options)


def solve(problem: FlowProblem, *, method: str, **options: object) -> FlowResult:
    """Solve a minimum or maximum cost flow problem with a named method.

    Parameters
    ----------
    problem : FlowProblem
    method : str
        ``"network_simplex"``, ``"cycle_canceling"`` or
        ``"successive_shortest_paths"`` (see :func:`methods`).
    **options
        Options of the method (see :func:`prepare`).

    Returns
    -------
    FlowResult
        Optimal flow and potentials, or the certificate of infeasibility
        (a violated cut) or of unboundedness (an improving cycle of arcs
        without upper bound).

    Examples
    --------
    >>> from protee.graph import Digraph
    >>> g = Digraph.from_arcs(3, [(0, 1), (1, 2), (0, 2)])
    >>> p = FlowProblem(g, upper=(2, 2, 1), cost=(1, 1, 3), supply=(3, 0, -3))
    >>> r = solve(p, method="network_simplex")
    >>> r.status, r.objective, r.flow
    (<Status.OPTIMAL: 'optimal'>, 7, (2, 2, 1))
    """
    return prepare(problem, method=method, **options).solve()
