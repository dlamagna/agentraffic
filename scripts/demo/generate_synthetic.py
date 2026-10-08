"""Synthetic runs and fixtures for the public site.

Usage::

    python -m scripts.demo.generate_synthetic [--public ui/data/public]

Reads only the public aggregates (``summary.json`` and ``workflow.json`` in ``--public``) and
writes, deterministically (fixed seed, stdlib only)::

    <public>/runs.json                          500 / 481 / 500 synthetic runs, same schema as the
                                                private runs.json, ``"synthetic": true`` on the
                                                document and on every run
    <public>/fixtures/index.json                one synthetic fixture per topology x task
    <public>/fixtures/<topology>/<task>.{response,events}.json

Method
------
Per topology, per-run metrics come from a Gaussian copula: the real Spearman matrix (without the
duplicate and constant metrics) is converted with ``r = 2 sin(pi rho / 6)``, repaired to the nearest
correlation matrix (Higham 2002 alternating projections), and sampled from ``N(0, R)``; each column
goes through the normal CDF and the inverse CDF of the real distribution (the public quantile
tables; linear or log interpolation, counts rounded). The sample is fixed (stratified normal scores,
whitened to unit sample covariance), and ``R`` is then calibrated on it: the latent correlation is
nudged until the Spearman matrix of the *stored* values (after snapping, rounding to 5 digits)
is close to the target, using exact uniform margins (Phi(x) replaced by the sample's own
CDF). A last rank-swap step (margins stay exact) closes what a Gaussian copula cannot reach with
heavily tied metrics such as the discussion-call count. A single draw of 500 runs would miss by
~0.1 on some of the ~300 pairs.

Timelines are then built from the sampled metrics with each topology's structure. Validation
(asserted): every pair's rho within +-0.05 per topology; medians and IQRs match the aggregates;
the pooled matrix is within +-0.1 of ``groups.all``. Nothing is written otherwise (exit 1).
"""

from __future__ import annotations

import argparse
import hashlib
import heapq
import json
import math
import random
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.demo import check_public as cp  # noqa: E402
from scripts.demo.analysis_outliers import annotate_runs  # noqa: E402
from scripts.demo.export_results import (  # noqa: E402
    CALL_FIELDS,
    SCHEMA_VERSION,
    STAGE_CODES,
    dumps_runs,
    sig,
)
from scripts.demo.generate_fixtures import (  # noqa: E402
    CATEGORY_TO_TASK,
    CONFIG_JS,
    TASKS,
    TOPOLOGIES,
    TOPOLOGY_LABELS,
    LeakError,
    assert_no_leaks,
    discussion_iats,
    dumps,
    iat_summary,
    parse_example_tasks,
    percentile,
    render_fixture,
)
from scripts.demo.sse_events import build_events  # noqa: E402

GENERATOR = "scripts/demo/generate_synthetic.py"
PUBLIC_DIR = REPO_ROOT / "ui" / "data" / "public"
SEED = 20260101
ENDPOINT = "http://llm:8000/chat"
NOMINAL_START = "2026-01-01T00:00:00"  # nominal: synthetic runs were not recorded
N_AGENTS = 4
MAX_ITER = 3
MAX_ROUNDS = 3
MAX_WORKERS = 5
TOL_RHO = 0.05  # spec: per-topology pairwise Spearman
GAIN = 1.5  # calibration step gain
TOL_CALIB = 0.025  # calibration target, leaves margin below TOL_RHO
TOL_POOLED = 0.1
TOL_MARGIN = 0.15  # median / IQR error, in units of max(IQR, 10% of |median|)
OUTPUT_CAP = 6144
ROLES = ("planner", "researcher", "executor", "critic")


# ---------------------------------------------------------------------------
# Normal CDF and inverse, linear algebra, Higham (stdlib only)
# ---------------------------------------------------------------------------


def norm_cdf(x: float) -> float:
    return 0.5 * math.erfc(-x / math.sqrt(2.0))


_A = (
    -3.969683028665376e01,
    2.209460984245205e02,
    -2.759285104469687e02,
    1.383577518672690e02,
    -3.066479806614716e01,
    2.506628277459239e00,
)
_B = (
    -5.447609879822406e01,
    1.615858368580409e02,
    -1.556989798598866e02,
    6.680131188771972e01,
    -1.328068155288572e01,
)
_C = (
    -7.784894002430293e-03,
    -3.223964580411365e-01,
    -2.400758277161838e00,
    -2.549732539343734e00,
    4.374664141464968e00,
    2.938163982698783e00,
)
_D = (7.784695709041462e-03, 3.224671290700398e-01, 2.445134137142996e00, 3.754408661907416e00)


def norm_ppf(p: float) -> float:
    """Inverse normal CDF: Acklam's rational approximation plus one Halley refinement step."""
    if not 0.0 < p < 1.0:
        raise ValueError("p must be in (0, 1)")
    if p < 0.02425:
        q = math.sqrt(-2 * math.log(p))
        x = (((((_C[0] * q + _C[1]) * q + _C[2]) * q + _C[3]) * q + _C[4]) * q + _C[5]) / (
            (((_D[0] * q + _D[1]) * q + _D[2]) * q + _D[3]) * q + 1
        )
    elif p > 1 - 0.02425:
        q = math.sqrt(-2 * math.log(1 - p))
        x = -(((((_C[0] * q + _C[1]) * q + _C[2]) * q + _C[3]) * q + _C[4]) * q + _C[5]) / (
            (((_D[0] * q + _D[1]) * q + _D[2]) * q + _D[3]) * q + 1
        )
    else:
        q = p - 0.5
        r = q * q
        x = (
            (((((_A[0] * r + _A[1]) * r + _A[2]) * r + _A[3]) * r + _A[4]) * r + _A[5])
            * q
            / (((((_B[0] * r + _B[1]) * r + _B[2]) * r + _B[3]) * r + _B[4]) * r + 1)
        )
    e = norm_cdf(x) - p
    u = e * math.sqrt(2 * math.pi) * math.exp(x * x / 2)
    return x - u / (1 + x * u / 2)


def cholesky(a: list[list[float]]) -> list[list[float]]:
    """Lower-triangular L with L L^T = a; ValueError if a is not positive definite."""
    n = len(a)
    low = [[0.0] * n for _ in range(n)]
    for i in range(n):
        for j in range(i + 1):
            s = a[i][j] - sum(low[i][k] * low[j][k] for k in range(j))
            if i == j:
                if s <= 1e-12:
                    raise ValueError("matrix is not positive definite")
                low[i][i] = math.sqrt(s)
            else:
                low[i][j] = s / low[j][j]
    return low


def eigh(a: list[list[float]]) -> tuple[list[float], list[list[float]]]:
    """Eigenvalues and eigenvectors (columns of V) of a symmetric matrix: cyclic Jacobi."""
    n = len(a)
    m = [row[:] for row in a]
    v = [[1.0 if i == j else 0.0 for j in range(n)] for i in range(n)]
    for _ in range(80):
        off = sum(m[i][j] ** 2 for i in range(n) for j in range(i + 1, n))
        if off < 1e-22:
            break
        for p in range(n - 1):
            for q in range(p + 1, n):
                apq = m[p][q]
                if abs(apq) < 1e-300:
                    continue
                theta = (m[q][q] - m[p][p]) / (2.0 * apq)
                t = math.copysign(1.0, theta) / (abs(theta) + math.sqrt(theta * theta + 1.0))
                c = 1.0 / math.sqrt(t * t + 1.0)
                s = t * c
                for k in range(n):
                    kp, kq = m[k][p], m[k][q]
                    m[k][p], m[k][q] = c * kp - s * kq, s * kp + c * kq
                for k in range(n):
                    pk, qk = m[p][k], m[q][k]
                    m[p][k], m[q][k] = c * pk - s * qk, s * pk + c * qk
                for k in range(n):
                    kp, kq = v[k][p], v[k][q]
                    v[k][p], v[k][q] = c * kp - s * kq, s * kp + c * kq
    return [m[i][i] for i in range(n)], v


def _project_psd(a: list[list[float]], floor: float) -> list[list[float]]:
    n = len(a)
    vals, v = eigh(a)
    vals = [max(x, floor) for x in vals]
    out = [[0.0] * n for _ in range(n)]
    for i in range(n):
        for j in range(i, n):
            x = sum(v[i][k] * vals[k] * v[j][k] for k in range(n))
            out[i][j] = out[j][i] = x
    return out


def nearest_correlation(
    a: list[list[float]], floor: float = 1e-6, tol: float = 1e-10, max_iter: int = 300
) -> list[list[float]]:
    """Higham (2002) alternating projections with Dykstra's correction: nearest correlation."""
    n = len(a)
    y = [[(a[i][j] + a[j][i]) / 2 for j in range(n)] for i in range(n)]
    ds = [[0.0] * n for _ in range(n)]
    for _ in range(max_iter):
        r = [[y[i][j] - ds[i][j] for j in range(n)] for i in range(n)]
        x = _project_psd(r, floor)
        ds = [[x[i][j] - r[i][j] for j in range(n)] for i in range(n)]
        y_new = [row[:] for row in x]
        for i in range(n):
            y_new[i][i] = 1.0
        diff = math.sqrt(sum((y_new[i][j] - y[i][j]) ** 2 for i in range(n) for j in range(n)))
        y = y_new
        if diff < tol:
            break
    return y


def make_pd_correlation(a: list[list[float]]) -> tuple[list[list[float]], list[list[float]]]:
    """(R, chol(R)): Higham repair, then shrink towards I until the Cholesky factor exists."""
    r = nearest_correlation(a)
    n = len(r)
    for delta in (0.0, 1e-9, 1e-7, 1e-5, 1e-4, 1e-3, 1e-2):
        cand = [
            [(1 - delta) * r[i][j] + (delta if i == j else 0.0) for j in range(n)] for i in range(n)
        ]
        try:
            return cand, cholesky(cand)
        except ValueError:
            continue
    raise ValueError("cannot make the correlation matrix positive definite")


# ---------------------------------------------------------------------------
# Spearman
# ---------------------------------------------------------------------------


def avg_ranks(xs: list[float]) -> list[float]:
    order = sorted(range(len(xs)), key=xs.__getitem__)
    ranks = [0.0] * len(xs)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and xs[order[j + 1]] == xs[order[i]]:
            j += 1
        r = (i + j) / 2.0 + 1.0
        for k in range(i, j + 1):
            ranks[order[k]] = r
        i = j + 1
    return ranks


def standardise(xs: list[float]) -> list[float] | None:
    n = len(xs)
    mu = sum(xs) / n
    sd = math.sqrt(sum((x - mu) ** 2 for x in xs))
    return None if sd < 1e-12 else [(x - mu) / sd for x in xs]


def spearman_matrix(cols: list[list[float]]) -> list[list[float | None]]:
    """Spearman rho (average ranks) of columns; None where a column is constant."""
    std = [standardise(avg_ranks(c)) for c in cols]
    k = len(cols)
    out: list[list[float | None]] = [[None] * k for _ in range(k)]
    for i in range(k):
        for j in range(i, k):
            if std[i] is None or std[j] is None:
                continue
            a, b = std[i], std[j]
            out[i][j] = out[j][i] = 1.0 if i == j else sum(x * y for x, y in zip(a, b))
    return out


# ---------------------------------------------------------------------------
# Marginals
# ---------------------------------------------------------------------------


class Margin:
    """Inverse CDF of a real metric distribution from its quantile table."""

    def __init__(self, grid: list[float], values: list[float]) -> None:
        self.p = [g / 100.0 for g in grid]
        self.v = [float(x) for x in values]
        self.const = len(set(self.v)) == 1
        self.integer = all(x.is_integer() for x in self.v)
        self.log = min(self.v) > 0 and max(self.v) / min(self.v) >= 10

    def inv(self, u: float) -> float:
        if self.const:
            return self.v[0]
        u = min(max(u, 0.0), 1.0)
        i = min(max(bisect_right(self.p, u) - 1, 0), len(self.p) - 2)
        v0, v1 = self.v[i], self.v[i + 1]
        if v0 == v1:
            x = v0
        else:
            f = (u - self.p[i]) / (self.p[i + 1] - self.p[i])
            x = (
                math.exp(math.log(v0) + f * (math.log(v1) - math.log(v0)))
                if self.log
                else v0 + f * (v1 - v0)
            )
        return float(round(x)) if self.integer else x


def bisect_right(a: list[float], x: float) -> int:
    lo, hi = 0, len(a)
    while lo < hi:
        mid = (lo + hi) // 2
        if x < a[mid]:
            hi = mid
        else:
            lo = mid + 1
    return lo


# ---------------------------------------------------------------------------
# Structure: how many discussion calls a topology can produce
# ---------------------------------------------------------------------------


def structure_table(topology: str) -> dict[int, tuple[int, ...]]:
    """Valid discussion-call totals -> rounds per iteration (fewest iterations first)."""
    table: dict[int, tuple[int, ...]] = {}
    for k in range(1, MAX_ITER + 1):
        if topology == "vertical":
            table.setdefault(12 * k, (MAX_ROUNDS,) * k)
            continue
        per_round = 4 if topology == "horizontal" else 12
        for m in range(k, MAX_ROUNDS * k + 1):  # total rounds over k iterations
            base, rem = divmod(m, k)
            rounds = tuple(base + 1 if i < rem else base for i in range(k))
            table.setdefault(k + per_round * m, rounds)
    return table


def snap_count(table: dict[int, tuple[int, ...]], n: float) -> int:
    return min(table, key=lambda v: (abs(v - n), v))


# ---------------------------------------------------------------------------
# Copula sampling per topology
# ---------------------------------------------------------------------------


def classify_metrics(keys: list[str], quant: dict, rho: list[list[float]]) -> dict:
    """Constants, duplicates (source index) and the independent metrics of one topology."""
    const, dup, indep = {}, {}, []
    for j, k in enumerate(keys):
        q = quant[k]
        if len(set(q)) == 1:
            const[j] = q[0]
            continue
        src = next(
            (i for i in indep if quant[keys[i]] == q and (rho[i][j] or 0) > 0.9999),
            None,
        )
        if src is None:
            indep.append(j)
        else:
            dup[j] = src
    return {"const": const, "dup": dup, "indep": indep}


def base_sample(n: int, k: int, rng: random.Random) -> list[list[float]]:
    """n x k normal scores: stratified per column, whitened to exactly unit sample covariance."""
    cols = []
    for _ in range(k):
        perm = list(range(n))
        rng.shuffle(perm)
        cols.append([norm_ppf((r + 0.5) / n) for r in perm])
    z = [[cols[j][i] for j in range(k)] for i in range(n)]
    cov = [[sum(z[t][a] * z[t][b] for t in range(n)) / n for b in range(k)] for a in range(k)]
    low = cholesky(cov)
    out = []
    for row in z:  # solve low w = row
        w = [0.0] * k
        for i in range(k):
            w[i] = (row[i] - sum(low[i][m] * w[m] for m in range(i))) / low[i][i]
        out.append(w)
    return out


def step_inverse(probs: dict[int, float], u: float) -> int:
    """Inverse CDF of a discrete distribution given as {value: probability}."""
    acc = 0.0
    for v in sorted(probs):
        acc += probs[v]
        if u < acc:
            return v
    return max(probs)


def uniform_scores(xs: list[float]) -> list[float]:
    """Empirical normal CDF of a sample: (rank - 1/2) / n, i.e. Phi(x) with exact uniform margins."""
    n = len(xs)
    order = sorted(range(n), key=xs.__getitem__)
    out = [0.0] * n
    for rank, i in enumerate(order):
        out[i] = (rank + 0.5) / n
    return out


def refine_by_swaps(
    cols: list[list[float]],
    target: list[list[float]],
    rng: random.Random,
    tol: float,
    max_attempts: int = 600_000,
) -> tuple[list[list[float]], int]:
    """Pairwise-swap values inside columns (margins stay exact) until every |rho error| <= tol.

    A Gaussian copula cannot reach every Spearman matrix once a metric is heavily tied (e.g. the
    discussion-call count has 3 levels): the latent correlations it would need are not jointly
    positive semidefinite. Swapping two entries of column c changes its Spearman correlation with
    column b by (z_c[j] - z_c[i]) (z_b[i] - z_b[j]) (z = standardised average ranks), so each trial
    costs O(k); a swap is kept when it lowers the sum of squared errors.
    """
    k = len(cols)
    n = len(cols[0])
    cols = [c[:] for c in cols]
    z = [standardise(avg_ranks(c)) or [0.0] * n for c in cols]
    cur = [[sum(a * b for a, b in zip(z[x], z[y])) for y in range(k)] for x in range(k)]

    def worst() -> tuple[float, list[int]]:
        errs = [max(abs(cur[x][y] - target[x][y]) for y in range(k) if y != x) for x in range(k)]
        return max(errs), [x for x in range(k) if errs[x] > tol]

    top, bad = worst()
    attempts = 0
    while top > tol and attempts < max_attempts:
        for _ in range(3000):
            attempts += 1
            c = rng.choice(bad) if bad and rng.random() < 0.8 else rng.randrange(k)
            i, j = rng.randrange(n), rng.randrange(n)
            if cols[c][i] == cols[c][j]:
                continue
            zc = z[c]
            d = zc[j] - zc[i]
            delta = 0.0
            news = []
            for b in range(k):
                if b == c:
                    continue
                zb = z[b]
                nv = cur[c][b] + d * (zb[i] - zb[j])
                e0 = cur[c][b] - target[c][b]
                e1 = nv - target[c][b]
                delta += e1 * e1 - e0 * e0
                news.append((b, nv))
            if delta < 0:
                cols[c][i], cols[c][j] = cols[c][j], cols[c][i]
                zc[i], zc[j] = zc[j], zc[i]
                for b, nv in news:
                    cur[c][b] = cur[b][c] = nv
        top, bad = worst()
    return cols, attempts


def sample_topology(
    topology: str,
    summary: dict,
    keys: list[str],
    rng: random.Random,
    count_probs: dict[int, float] | None = None,
) -> tuple[list[list[float]], dict]:
    """Synthetic metric rows (n x 29, 5 significant digits) and the calibration report."""
    corr = summary["correlations"]["groups"][topology]
    n = corr["n"]
    rho = corr["rho"]
    grid = summary["quantile_grid"]
    quant = summary["quantiles"][topology]
    cls = classify_metrics(keys, quant, rho)
    indep = cls["indep"]
    k = len(indep)
    margins = {j: Margin(grid, quant[keys[j]]) for j in range(len(keys))}
    table = structure_table(topology)
    n_idx = keys.index("disc_n_requests")
    target = [[rho[a][b] for b in indep] for a in indep]
    latent0 = [[2 * math.sin(math.pi * target[a][b] / 6) for b in range(k)] for a in range(k)]
    z = base_sample(n, k, rng)

    def columns(chol: list[list[float]]) -> list[list[float]]:
        x = [[sum(chol[j][m] * row[m] for m in range(j + 1)) for j in range(k)] for row in z]
        cols = []
        for c, j in enumerate(indep):
            m = margins[j]
            vals = [m.inv(u) for u in uniform_scores([row[c] for row in x])]
            if j == n_idx and count_probs:
                vals = [
                    float(step_inverse(count_probs, u))
                    for u in uniform_scores([row[c] for row in x])
                ]
            elif j == n_idx:
                vals = [float(snap_count(table, v)) for v in vals]
            cols.append([float(sig(v, 5)) for v in vals])
        return cols

    r, chol = make_pd_correlation(latent0)
    best: tuple[float, list[list[float]]] | None = None
    history = []
    stall = 0
    for it in range(30):
        cols = columns(chol)
        s = spearman_matrix(cols)
        err = max(abs(target[a][b] - (s[a][b] or 0.0)) for a in range(k) for b in range(a + 1, k))
        history.append(err)
        if best is None or err < best[0] - 1e-4:
            stall = 0
        else:
            stall += 1
        if best is None or err < best[0]:
            best = (err, cols)
        if stall >= 6:
            break
        if err <= TOL_CALIB:
            break
        step = [
            [
                (
                    2 * math.sin(math.pi * target[a][b] / 6)
                    - 2 * math.sin(math.pi * (s[a][b] or 0.0) / 6)
                    if a != b
                    else 0.0
                )
                for b in range(k)
            ]
            for a in range(k)
        ]
        r = [
            [
                max(-0.9995, min(0.9995, r[a][b] + GAIN * step[a][b])) if a != b else 1.0
                for b in range(k)
            ]
            for a in range(k)
        ]
        try:
            chol = cholesky(r)
        except ValueError:
            r, chol = make_pd_correlation(r)
    assert best is not None
    cols, swaps = refine_by_swaps(
        best[1], target, random.Random(f"{SEED}-swap-{topology}"), TOL_CALIB
    )
    full: list[list[float]] = [[] for _ in keys]
    for c, j in enumerate(indep):
        full[j] = cols[c]
    for j, src in cls["dup"].items():
        full[j] = list(full[src])
    for j, v in cls["const"].items():
        full[j] = [float(v)] * n
    rows = [[full[j][i] for j in range(len(keys))] for i in range(n)]
    return rows, {"iterations": len(history), "calibration_error": history, "swap_attempts": swaps}


def validate_topology(
    topology: str, summary: dict, keys: list[str], rows: list[list[float]]
) -> dict:
    corr = summary["correlations"]["groups"][topology]["rho"]
    cols = [[r[j] for r in rows] for j in range(len(keys))]
    s = spearman_matrix(cols)
    worst, pair = 0.0, None
    for a in range(len(keys)):
        for b in range(a + 1, len(keys)):
            if s[a][b] is None:
                continue
            e = abs(s[a][b] - corr[a][b])
            if e > worst:
                worst, pair = e, (keys[a], keys[b])
    agg = summary["aggregates"]["by_topology"][topology]
    med_err, iqr_err = [], []
    for j, k in enumerate(keys):
        t = agg[k]
        scale = max(t["p75"] - t["p25"], 0.1 * abs(t["median"]), 1e-12)
        col = cols[j]
        q1, q2, q3 = (percentile(col, q) for q in (25, 50, 75))
        med_err.append((abs(q2 - t["median"]) / scale, k))
        iqr_err.append((abs((q3 - q1) - (t["p75"] - t["p25"])) / scale, k))
    return {
        "n": len(rows),
        "max_rho_error": worst,
        "max_rho_pair": pair,
        "median_error": max(med_err),
        "iqr_error": max(iqr_err),
    }


def validate_pooled(summary: dict, keys: list[str], all_rows: list[list[float]]) -> dict:
    cols = [[r[j] for r in all_rows] for j in range(len(keys))]
    s = spearman_matrix(cols)
    target = summary["correlations"]["groups"]["all"]["rho"]
    worst, pair = 0.0, None
    for a in range(len(keys)):
        for b in range(a + 1, len(keys)):
            if s[a][b] is None:
                continue
            e = abs(s[a][b] - target[a][b])
            if e > worst:
                worst, pair = e, (keys[a], keys[b])
    return {"n": len(all_rows), "max_rho_error": worst, "max_rho_pair": pair}


# ---------------------------------------------------------------------------
# Timelines
# ---------------------------------------------------------------------------


def lognorm(rng: random.Random, sigma: float) -> float:
    """Mean-one log-normal multiplier."""
    return math.exp(sigma * rng.gauss(0, 1) - sigma * sigma / 2)


class Call:
    __slots__ = (
        "t",
        "d",
        "stage",
        "agent",
        "peer",
        "round",
        "pt",
        "ct",
        "qw",
        "it",
        "fixed",
        "mult",
    )

    def __init__(self, stage, agent, peer, rnd, it, mult=1.0):
        self.t = 0.0
        self.d = 0.0
        self.stage = stage
        self.agent = agent
        self.peer = peer
        self.round = rnd
        self.pt = 0
        self.ct = 0
        self.qw = 0.0
        self.it = it
        self.fixed = 0.0  # runaway extra seconds, not scaled
        self.mult = mult


def discussion_calls(topology: str, rounds: int, it: int) -> list[list[Call]]:
    """Discussion calls of one iteration as ordered phases (a phase's calls run in parallel)."""
    phases: list[list[Call]] = []
    if topology == "horizontal":
        for rd in range(1, rounds + 1):
            for a in range(N_AGENTS):
                phases.append([Call(1, a, a - 1 if a else -1, rd, it)])
        phases.append([Call(2, -1, -1, None, it, 2.1)])
    elif topology == "vertical":
        for rd in range(1, rounds + 1):
            phases.append([Call(1, 0, -1, rd, it, 1.1)])
            phases.append([Call(1, a, 0, rd, it, 0.95) for a in range(1, N_AGENTS)])
    else:
        for rd in range(1, rounds + 1):
            msgs = [
                Call(1, s, p, rd, it) for s in range(N_AGENTS) for p in range(N_AGENTS) if s != p
            ]
            phases.append(msgs)  # pool-limited, see schedule()
        phases.append([Call(2, -1, -1, None, it, 3.0)])
    return phases


def schedule(topology: str, phases: list[list[Call]], base: list[float], f: float) -> float:
    """Place the calls (t, d set) with duration scale f; return the span of the iteration."""
    gap = 0.004 * f
    cursor = 0.0
    i = 0
    for phase in phases:
        if topology == "full_mesh" and len(phase) == 12:
            free = [cursor] * MAX_WORKERS
            heapq.heapify(free)
            end_all = cursor
            for n_msg, c in enumerate(phase):
                c.d = base[i] * f + c.fixed
                i += 1
                start = heapq.heappop(free) + (
                    0.0015 * (n_msg % MAX_WORKERS) if n_msg < MAX_WORKERS else 0.002
                )
                c.t = start
                heapq.heappush(free, start + c.d)
                end_all = max(end_all, start + c.d)
            cursor = end_all + gap
        else:
            end_all = cursor
            for j, c in enumerate(phase):
                c.d = base[i] * f + c.fixed
                i += 1
                c.t = cursor + 0.0012 * j
                end_all = max(end_all, c.t + c.d)
            cursor = end_all + gap
    return cursor - gap


def solve_scale(topology: str, phases: list[list[Call]], base: list[float], target: float) -> float:
    lo, hi = math.log(0.05), math.log(20.0)
    for _ in range(40):
        mid = (lo + hi) / 2
        if schedule(topology, phases, base, math.exp(mid)) < target:
            lo = mid
        else:
            hi = mid
    f = math.exp((lo + hi) / 2)
    schedule(topology, phases, base, f)
    return f


def build_timeline(
    topology: str, m: dict, rounds: list[int], wf: dict, rng: random.Random
) -> list[Call]:
    """All LLM calls of one synthetic run, in seconds from an arbitrary origin."""
    lat = max(m["disc_mean_latency_s"], 0.3)
    total_d = max(m["disc_duration_s"], 1.0)
    n_total = sum(
        (4 * r + 1) if topology == "horizontal" else (12 * r + 1) if topology == "full_mesh" else 12
        for r in rounds
    )
    sigma = 0.3
    cps = max(m["completion_tokens_per_s_mean"], 20.0)
    total_tokens = max(m["disc_total_tokens"], 400.0)
    q50 = max(m["llm_ttft_p50_mean_s"], 0.005) * 1000
    q95 = max(m["llm_ttft_p95_mean_s"], 0.006) * 1000
    sig_q = min(max(math.log(max(q95 / q50, 1.01)) / 1.645, 0.15), 1.0)
    calls: list[Call] = []
    cursor = 0.0
    n_done = 0
    for it, r in enumerate(rounds):
        n_it = (
            (4 * r + 1)
            if topology == "horizontal"
            else (12 * r + 1) if topology == "full_mesh" else 12
        )
        d_it = total_d * n_it / n_total
        rec = Call(0, -1, -1, None, it)
        rec.t, rec.d = cursor, wf["dur"][0] * lognorm(rng, 0.2)
        tok = wf["tok"][0] * lognorm(rng, 0.2)
        rec.ct = max(8, int(tok * 0.4))
        rec.pt = max(20, int(tok) - rec.ct)
        rec.qw = round(q50 * 1.5 * lognorm(rng, 0.3), 1)
        calls.append(rec)
        cursor += rec.d + 0.003 + rng.random() * 0.02
        phases = discussion_calls(topology, r, it)
        flat = [c for ph in phases for c in ph]
        base = [lat * c.mult * lognorm(rng, sigma) for c in flat]
        span1 = schedule(topology, phases, base, 1.0)
        extra = d_it - span1
        if extra > max(20.0, 0.5 * span1):  # runaway generations absorb the excess
            k = min(3, max(1, math.ceil(extra / 85.0)))
            pool = [c for c in flat if c.stage == 1]
            for c in rng.sample(pool, min(k, len(pool))):
                c.fixed = min(90.0, extra / k)
                c.mult = 0.0
        solve_scale(topology, phases, base, d_it)
        # tokens and queue waits
        w = []
        for c in flat:
            late = c.round is not None and c.round > 1
            if topology == "vertical":
                wt = (2.5 if late else 0.15) if c.agent == 0 else 1.0 + 0.3 * ((c.round or 1) - 1)
            elif c.stage == 2:
                wt = 3.0 * 6.5
            else:
                wt = 6.5 if late else 1.0
            w.append(wt * lognorm(rng, 0.1))
        cts = []
        for c in flat:
            ct = c.d * cps * lognorm(rng, 0.15)
            cts.append(float(OUTPUT_CAP) if c.fixed else min(ct, OUTPUT_CAP - 144.0))
        budget = total_tokens * n_it / n_total
        free_ct = sum(x for x, c in zip(cts, flat) if not c.fixed)
        if budget - sum(cts) < 40.0 * len(flat) and free_ct > 0:
            keep = sum(x for x, c in zip(cts, flat) if c.fixed)
            scale = max(budget * 0.4 - keep, budget * 0.1) / free_ct
            cts = [x if c.fixed else x * scale for x, c in zip(cts, flat)]
        sw = sum(w)
        pscale = max(budget - sum(cts), 40.0 * len(flat)) / sw
        mean_pt = (budget - sum(cts)) / len(flat) if budget > sum(cts) else 100.0
        for c, wt, ct in zip(flat, w, cts):
            c.pt = max(20, int(round(wt * pscale)))
            c.ct = max(8, int(round(ct)))
            ratio = max(c.pt, 1) / max(mean_pt, 1.0)
            c.qw = round(
                min(
                    max(q50 * ratio**0.5 * math.exp(sig_q * 0.4 * rng.gauss(0, 1)), 3.0), c.d * 700
                ),
                1,
            )
        for c in flat:
            c.t += cursor
            calls.append(c)
        n_done += n_it
        cursor = max(c.t + c.d for c in flat) + 0.004
        # execution: one call per expert, in parallel
        order = list(range(N_AGENTS))
        rng.shuffle(order)
        ends = []
        for j, a in enumerate(order):
            c = Call(3, a, -1, None, it)
            c.t = cursor + 0.0012 * j
            c.d = wf["dur"][3] * (lat / wf["lat_med"]) ** 0.6 * lognorm(rng, 0.3)
            tok = wf["tok"][3] * lognorm(rng, 0.3)
            c.ct = max(8, int(tok * 0.45))
            c.pt = max(20, int(tok) - c.ct)
            c.qw = round(q50 * 2 * lognorm(rng, 0.3), 1)
            calls.append(c)
            ends.append(c.t + c.d)
        cursor = max(ends) + 0.004
        ev = Call(4, -1, -1, None, it)
        ev.t, ev.d = cursor, wf["dur"][4] * lognorm(rng, 0.25)
        tok = wf["tok"][4] * lognorm(rng, 0.2)
        ev.ct = max(8, int(tok * 0.05))
        ev.pt = max(20, int(tok) - ev.ct)
        ev.qw = round(q50 * 3 * lognorm(rng, 0.3), 1)
        calls.append(ev)
        cursor += ev.d + 0.01 + rng.random() * 0.03
    fo = Call(5, -1, -1, None, len(rounds) - 1)
    fo.t, fo.d = cursor, wf["dur"][5] * lognorm(rng, 0.3)
    tok = wf["tok"][5] * lognorm(rng, 0.3)
    fo.ct = max(8, int(tok * 0.25))
    fo.pt = max(20, int(tok) - fo.ct)
    fo.qw = round(q50 * 4 * lognorm(rng, 0.3), 1)
    calls.append(fo)
    return calls


def encode_calls(calls: list[Call]) -> list[list[Any]]:
    ordered = sorted(enumerate(calls), key=lambda x: (x[1].t, x[0]))
    t0 = ordered[0][1].t
    rows = []
    for _, c in ordered:
        rows.append(
            [
                int(round((c.t - t0) * 1000)),
                max(10, int(round(c.d * 100)) * 10),
                c.stage,
                c.agent,
                c.peer,
                c.round,
                c.pt,
                c.ct,
                c.qw,
            ]
        )
    return rows


# ---------------------------------------------------------------------------
# Runs document
# ---------------------------------------------------------------------------


def workflow_constants(workflow: dict, topology: str) -> dict:
    g = workflow["groups"]["all"][topology]
    pr = g["stages"]["per_run"]
    calls, toks, llm = pr["calls"], pr["tokens"], pr["llm_time_s"]
    dur = [llm[i] / calls[i] if calls[i] else 3.0 for i in range(6)]
    tok = [toks[i] / calls[i] if calls[i] else 1000.0 for i in range(6)]
    return {"dur": dur, "tok": tok}


def weighted_choice(rng: random.Random, counts: dict) -> int:
    keys = sorted(counts, key=int)
    return int(rng.choices(keys, weights=[counts[k] for k in keys])[0])


def run_id(index: int) -> str:
    h = hashlib.sha1(f"{SEED}-{index}".encode()).hexdigest()[:4]
    return f"syn-{index:04d}{h}"


def build_runs_doc(
    summary: dict, workflow: dict, report: dict
) -> tuple[dict, list[list[Call]], list[dict]]:
    keys = summary["correlations"]["metric_keys"]
    rows_by_topo: dict[str, list[list[float]]] = {}
    report["topologies"] = {}
    for topo in TOPOLOGIES:
        probs = None
        if topo == "vertical":  # n = 12 x iterations: the iteration counts are exact aggregates
            it = workflow["groups"]["all"][topo]["retries"]["iterations"]
            tot = sum(it.values())
            probs = {12 * int(k): v / tot for k, v in it.items()}
        rows, cal = sample_topology(
            topo, summary, keys, random.Random(f"{SEED}-copula-{topo}"), probs
        )
        rows_by_topo[topo] = rows
        report["topologies"][topo] = {**validate_topology(topo, summary, keys, rows), **cal}
    report["pooled"] = validate_pooled(
        summary, keys, [r for t in TOPOLOGIES for r in rows_by_topo[t]]
    )

    entries: list[dict] = []
    for topo in TOPOLOGIES:
        rng = random.Random(f"{SEED}-attrs-{topo}")
        rows = rows_by_topo[topo]
        n = len(rows)
        tasks_n = summary["aggregates"]["by_topology_task"][topo]
        task_list = [t for t in TASKS for _ in range(tasks_n[t]["disc_n_requests"]["n"])]
        assert len(task_list) == n, (topo, len(task_list), n)
        rng.shuffle(task_list)
        quality = workflow["groups"]["all"][topo]["quality"]
        scores = [weighted_choice(rng, quality["score_counts"]) for _ in range(n)]
        n_false = round((1 - quality["goal_rate"]) * n)
        lowest = sorted(range(n), key=lambda i: (scores[i], rng.random()))[:n_false]
        missed = set(lowest)
        per_round = workflow["groups"]["all"][topo]["consensus"]["per_round"]
        p_last = per_round[MAX_ROUNDS - 1]["rate"] if len(per_round) >= MAX_ROUNDS else 0.0
        table = structure_table(topo)
        for i in range(n):
            m = dict(zip(keys, rows[i]))
            rounds = table[int(m["disc_n_requests"])]
            entries.append(
                {
                    "topo": topo,
                    "task": task_list[i],
                    "row": rows[i],
                    "m": m,
                    "rounds": list(rounds),
                    "score": scores[i],
                    "goal": i not in missed,
                    "p_last": p_last,
                }
            )
    random.Random(f"{SEED}-order").shuffle(entries)

    wfc = {t: workflow_constants(workflow, t) for t in TOPOLOGIES}
    for t in TOPOLOGIES:
        wfc[t]["lat_med"] = summary["aggregates"]["by_topology"][t]["disc_mean_latency_s"]["median"]
    runs, rich = [], []
    for idx, e in enumerate(entries, start=1):
        rng = random.Random(f"{SEED}-run-{idx}")
        topo = e["topo"]
        rounds = e["rounds"]
        calls = build_timeline(topo, e["m"], rounds, wfc[topo], rng)
        rich.append(calls)
        rosters = []
        for _ in rounds:
            roster = list(ROLES)
            if rng.random() < 0.12:
                roster[2] = rng.choice(["researcher", "summarizer"])
            rosters.append(roster)
        last = rounds[-1]
        if topo == "vertical":
            consensus = False
        elif last < MAX_ROUNDS:
            consensus = True
        else:
            consensus = rng.random() < e["p_last"]
        rid = run_id(idx)
        run: dict[str, Any] = {
            "id": rid,
            "topology": topo,
            "task": e["task"],
            "task_id": rid,
            "experiment": 0,
            "fixture": False,
            "iterations": len(rounds),
            "score": e["score"],
            "goal_achieved": e["goal"],
            "consensus_reached": consensus,
            "discussion_rounds": last,
            "metrics": [sig(v, 5) for v in e["row"]],
            "roles": rosters[-1],
        }
        if any(r != rosters[0] for r in rosters):
            run["roles_by_iteration"] = rosters
        run["calls"] = encode_calls(calls)
        run["synthetic"] = True
        runs.append(run)

    doc = {
        "schema_version": SCHEMA_VERSION,
        "generator": GENERATOR,
        "synthetic": True,
        "notes": [
            "SYNTHETIC: every run was generated from the public aggregates (Gaussian copula on "
            "the real per-topology rank correlations and quantiles, then a timeline with each "
            "topology's structure). No run here was recorded.",
            "experiment: index into experiments. metrics: values in metric_keys order (5 "
            "significant digits).",
            "roles: expert roles of the final iteration in recruitment order; roles_by_iteration "
            "(only when the roster changed) lists every iteration's roster. Each iteration starts "
            "with its recruitment call.",
            "calls: every LLM call, sorted by start, columns in call_fields order. start_ms: since "
            "the run's first LLM call; dur_ms: call duration, multiple of 10 ms; stage: index into "
            "stage_codes; agent: recruitment position of the calling expert (-1 = orchestrator); "
            "peer: receiver (full mesh), solver/hub (star reviewers), chain predecessor "
            "(sequential discussion), -1 = none; round: discussion round (star: solver "
            "iteration), null outside the discussion; queue_wait_ms (= TTFT).",
        ],
        "experiments": ["synthetic"],
        "metric_keys": list(keys),
        "stage_codes": list(STAGE_CODES),
        "call_fields": list(CALL_FIELDS),
        "runs": runs,
    }
    return doc, rich, entries


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

_PHRASES = (
    "proposes the next step of the plan",
    "checks the previous contribution for gaps",
    "suggests a concrete way to split the work",
    "refines the shared outline",
    "raises a risk and a mitigation",
    "summarises what the group has agreed so far",
)


def _iso(offset_s: float) -> str:
    base = 1767225600.0  # 2026-01-01T00:00:00 UTC
    from datetime import datetime, timezone

    return datetime.fromtimestamp(base + offset_s, tz=timezone.utc).isoformat(
        timespec="microseconds"
    )


def build_response(run: dict, task_text: str, task_label: str) -> dict:
    """A synthetic ``response.json`` for a one-iteration run, with templated text."""
    topo = run["topology"]
    roles = run["roles"]
    fields = {f: i for i, f in enumerate(CALL_FIELDS)}
    rows = run["calls"]
    sources = lambda a: "Agent A" if a < 0 else f"agent-b-{a + 1}"  # noqa: E731
    reqs = []
    for seq, row in enumerate(rows, start=1):
        st = row[fields["stage"]]
        a, p, rd = row[fields["agent"]], row[fields["peer"]], row[fields["round"]]
        role = "orchestrator" if a < 0 else roles[a]
        dur = row[fields["dur_ms"]] / 1000.0
        phrase = _PHRASES[(seq + (a if a > 0 else 0)) % len(_PHRASES)]
        extra: dict[str, Any] = {}
        if st == 0:
            stage, label = "recruitment", "expert_recruitment"
            resp = json.dumps(
                {
                    "experts": [
                        {
                            "role": r,
                            "responsibilities": f"[synthetic] {r} duties for the {task_label}",
                        }
                        for r in roles
                    ],
                    "communication_structure": topo,
                    "reasoning": f"[synthetic] {topo} structure chosen for illustration.",
                }
            )
            prompt = f"[synthetic] recruit experts for a {task_label} task"
        elif st in (1, 2):
            stage = "decision"
            if st == 2:
                label, resp = (
                    "synthesize_discussion",
                    "[synthetic] orchestrator: merges the discussion into one decision.",
                )
                prompt = "[synthetic] synthesise the discussion"
            elif topo == "horizontal":
                label = f"horizontal_discussion_round{rd}"
                resp = f"[synthetic] {role}, round {rd}: {phrase}."
                prompt = f"[synthetic] {role}, round {rd}: contribute to the discussion"
            elif topo == "vertical":
                if a == 0:
                    label = f"vertical_solver_iter{rd}"
                    resp = f"[synthetic] {role}, round {rd}: drafts a solution and {phrase}."
                else:
                    label = f"vertical_reviewer_{role}_iter{rd}"
                    resp = f"[synthetic] {role}, round {rd}: reviews the draft and {phrase}."
                prompt = f"[synthetic] {role}, round {rd}: {'propose' if a == 0 else 'review'}"
            else:
                label = f"full_mesh_message_round{rd}_agent{a + 1}_to_agent{p + 1}"
                resp = f"[synthetic] {role} to {roles[p]}, round {rd}: {phrase}."
                prompt = f"[synthetic] {role} writes to {roles[p]}, round {rd}"
                extra = {"sender_role": role, "receiver_role": roles[p]}
            if rd is not None:
                extra["round"] = rd
        elif st == 3:
            stage, label = "execution", f"execute_{role}"
            resp = f"[synthetic] {role}: delivers its part of the plan."
            prompt = f"[synthetic] {role}: execute your subtask"
        elif st == 4:
            stage, label = "evaluation", "evaluate_results"
            resp = "[synthetic] evaluator: scores the combined result."
            prompt = "[synthetic] evaluate the results"
        else:
            stage, label = "synthesis", "final_output"
            resp = f"[synthetic] final answer for the {task_label} task."
            prompt = "[synthetic] write the final output"
        pt, ct = row[fields["prompt_tokens"]], row[fields["completion_tokens"]]
        rid = hashlib.sha1(f"{run['id']}-{seq}".encode()).hexdigest()[:8]
        entry = {
            "seq": seq,
            "iteration": 0,
            "stage": stage,
            "label": label,
            "source": sources(a),
            "prompt": prompt,
            "response": resp,
            "endpoint": ENDPOINT,
            "error": False,
            "start_time_utc": _iso(row[fields["start_ms"]] / 1000.0),
            "request_id": rid,
            "llm_meta": {
                "request_id": rid,
                "latency_ms": int(row[fields["dur_ms"]]),
                "queue_wait_s": round(row[fields["queue_wait_ms"]] / 1000.0, 4),
                "prompt_tokens": pt,
                "completion_tokens": ct,
                "total_tokens": pt + ct,
            },
            "agent_role": role,
        }
        entry.update(extra)
        entry["duration_seconds"] = dur
        reqs.append(entry)

    last = run["discussion_rounds"]
    agreed = run["consensus_reached"]
    rounds_out = []
    for rd in range(1, last + 1):
        final_rd = rd == last
        if topo == "horizontal":
            rounds_out.append(
                {
                    "round": rd,
                    "responses": [
                        {
                            "expert": roles[a],
                            "index": a,
                            "response": f"[synthetic] {roles[a]}, round {rd}: {_PHRASES[(rd + a) % len(_PHRASES)]}."
                            + (" [CONSENSUS]" if agreed and final_rd else ""),
                            "consensus": bool(agreed and final_rd),
                        }
                        for a in range(N_AGENTS)
                    ],
                }
            )
        elif topo == "vertical":
            rounds_out.append(
                {
                    "iteration": rd,
                    "proposal": f"[synthetic] {roles[0]}, round {rd}: drafts a solution.",
                    "reviewer_responses": [
                        {
                            "reviewer": roles[a],
                            "critique": f"[synthetic] {roles[a]}, round {rd}: asks for one more revision.",
                            "approved": False,
                        }
                        for a in range(1, N_AGENTS)
                    ],
                    "all_approved": False,
                }
            )
        else:
            msgs = [
                {
                    "sender": roles[s],
                    "sender_index": s,
                    "receiver": roles[p],
                    "receiver_index": p,
                    "response": f"[synthetic] {roles[s]} to {roles[p]}, round {rd}: {_PHRASES[(rd + s + p) % len(_PHRASES)]}."
                    + (" [CONSENSUS]" if agreed and final_rd else ""),
                    "consensus": bool(agreed and final_rd),
                }
                for s in range(N_AGENTS)
                for p in range(N_AGENTS)
                if s != p
            ]
            rounds_out.append(
                {"round": rd, "messages": msgs, "all_consensus": bool(agreed and final_rd)}
            )
    score = run["score"]
    criteria = {
        k: max(0, min(100, score - 3 + 2 * i))
        for i, k in enumerate(
            ("completeness", "correctness", "clarity", "relevance", "actionability")
        )
    }
    evaluation = {
        "goal_achieved": run["goal_achieved"],
        "score": score,
        "criteria": criteria,
        "rationale": "[synthetic] generated rationale.",
        "feedback": "[synthetic] generated feedback.",
    }
    total_s = max(r[0] + r[1] for r in rows) / 1000.0
    return {
        "task_id": run["id"],
        "original_task": task_text,
        "completed": True,
        "iterations": 1,
        "duration_seconds": round(total_s, 2),
        "final_output": f"[synthetic] final answer for the {task_label} task.",
        "stages": {
            "recruitment": {
                "experts": [
                    {
                        "role": r,
                        "responsibilities": f"[synthetic] {r} duties for the {task_label}",
                        "endpoint": ENDPOINT,
                    }
                    for r in roles
                ],
                "communication_structure": topo,
                "reasoning": f"[synthetic] {topo} structure chosen for illustration.",
            },
            "decision": {
                "final_decision": "[synthetic] the group's merged decision.",
                "consensus_reached": agreed,
                "structure_used": topo,
                "discussion_rounds": rounds_out,
                "solver_role": roles[0] if topo == "vertical" else None,
                "reviewer_roles": roles[1:] if topo == "vertical" else list(roles),
            },
            "execution": {
                "outputs": [
                    {
                        "expert": roles[a],
                        "index": a,
                        "subtask": f"[synthetic] subtask for {roles[a]}",
                        "output": f"[synthetic] {roles[a]}: delivers its part of the plan.",
                        "success": True,
                    }
                    for a in range(N_AGENTS)
                ],
                "success_count": N_AGENTS,
                "failure_count": 0,
            },
            "evaluation": {**evaluation, "missing_aspects": []},
        },
        "iteration_history": [
            {
                "iteration": 0,
                "duration_seconds": round(total_s, 2),
                "recruitment": {"experts": list(roles), "structure": topo},
                "decision": {"consensus": agreed, "rounds": last},
                "execution": {"success": N_AGENTS, "failures": 0},
                "evaluation": evaluation,
            }
        ],
        "llm_requests": reqs,
    }


def pick_fixture_runs(doc: dict, summary: dict) -> dict[tuple[str, str], dict]:
    """Per topology x task: a one-iteration, goal-achieving run closest to the group median."""
    keys = doc["metric_keys"]
    i_n, i_d = keys.index("disc_n_requests"), keys.index("disc_duration_s")
    chosen = {}
    for topo in TOPOLOGIES:
        agg = summary["aggregates"]["by_topology"][topo]
        for task in TASKS:
            pool = [
                r
                for r in doc["runs"]
                if r["topology"] == topo
                and r["task"] == task
                and r["iterations"] == 1
                and r["goal_achieved"]
                and r["score"] >= 90
            ]

            def dist(r: dict) -> tuple[float, str]:
                dn = (r["metrics"][i_n] - agg["disc_n_requests"]["median"]) / max(
                    agg["disc_n_requests"]["median"], 1
                )
                dd = (r["metrics"][i_d] - agg["disc_duration_s"]["median"]) / max(
                    agg["disc_duration_s"]["median"], 1
                )
                return (dn * dn + dd * dd, r["id"])

            chosen[(topo, task)] = min(pool, key=dist)
    return chosen


def build_fixtures(doc: dict, summary: dict, example_tasks: dict[str, str]) -> dict[str, str]:
    chosen = pick_fixture_runs(doc, summary)
    labels = {t["key"]: t["label"] for t in summary["tasks"]}
    files: dict[str, str] = {}
    entries = []
    for (topo, task), run in chosen.items():
        run["fixture"] = True
        response = build_response(run, example_tasks[task], labels[task])
        part = render_fixture(topo, task, response, build_events)
        files.update(part)
        reqs = response["llm_requests"]
        disc = discussion_iats(reqs, topo)
        n_disc = sum(1 for r in reqs if r["stage"] == "decision")
        rel_r, rel_e = f"{topo}/{task}.response.json", f"{topo}/{task}.events.json"
        entries.append(
            {
                "topology": topo,
                "topology_label": TOPOLOGY_LABELS[topo],
                "task": task,
                "category": next(c for c, t in CATEGORY_TO_TASK.items() if t == task),
                "task_id": run["id"],
                "experiment": "synthetic",
                "recorded_start_utc": NOMINAL_START + "+00:00",
                "duration_s": response["duration_seconds"],
                "iterations": 1,
                "n_llm_calls": len(reqs),
                "n_discussion_calls": n_disc,
                "total_tokens": sum(r["llm_meta"]["total_tokens"] for r in reqs),
                "evaluation_score": run["score"],
                "discussion_iat": iat_summary(disc),
                "original_task": example_tasks[task],
                "matches_example_task": True,
                "truncated": False,
                "truncated_strings": 0,
                "synthetic": True,
                "files": {
                    "response": rel_r,
                    "response_bytes": len(part[rel_r].encode("utf-8")),
                    "events": rel_e,
                    "events_bytes": len(part[rel_e].encode("utf-8")),
                },
            }
        )
    index = {
        "schema_version": 1,
        "note": "synthetic runs generated from the public aggregates; nothing here was recorded",
        "synthetic": True,
        "generator": GENERATOR,
        "fixtures": entries,
    }
    files["index.json"] = dumps(index)
    return files


# ---------------------------------------------------------------------------
# Guards
# ---------------------------------------------------------------------------


def assert_no_private_text(files: dict[str, str], root: Path) -> None:
    """No real id, prompt or response text from ui/data/private/ in the output (if it exists)."""
    if not (root / cp.PRIVATE_DIR).is_dir():
        return
    ids, texts = cp.private_secrets(root)
    allowed = " ".join(cp.norm(t) for t in cp.committed_text(root))
    texts = {t for t in texts if t not in allowed}
    flen = cp.FINGERPRINT_LEN
    long_fps = {t for t in texts if len(t) >= flen}
    short_fps = [t for t in texts if len(t) < flen]
    for name, raw in files.items():
        hays = [cp.norm(raw)]
        if name.endswith(".json"):
            try:
                hays = [cp.norm(s) for s in cp.strings(json.loads(raw))]
            except ValueError:
                pass
        for ident in ids:
            if (ident in raw) if len(ident) > 8 else (f'"{ident}"' in raw):
                raise LeakError(f"{name}: real id {ident} from ui/data/private/")
        for hay in hays:
            if len(hay) < cp.MIN_TEXT_LEN:
                continue
            for i in range(len(hay) - flen + 1):
                if hay[i : i + flen] in long_fps:
                    raise LeakError(f"{name}: real text from ui/data/private/: {hay[i:i + flen]!r}")
            for fp in short_fps:
                if fp in hay:
                    raise LeakError(f"{name}: real text from ui/data/private/: {fp!r}")


def assert_validation(report: dict) -> list[str]:
    problems = []
    for topo, r in report["topologies"].items():
        if r["max_rho_error"] > TOL_RHO:
            problems.append(
                f"{topo}: max |rho error| {r['max_rho_error']:.3f} at {r['max_rho_pair']}"
            )
        for kind in ("median_error", "iqr_error"):
            if r[kind][0] > TOL_MARGIN:
                problems.append(f"{topo}: {kind} {r[kind][0]:.3f} for {r[kind][1]}")
    if report["pooled"]["max_rho_error"] > TOL_POOLED:
        problems.append(
            f"pooled: max |rho error| {report['pooled']['max_rho_error']:.3f} at "
            f"{report['pooled']['max_rho_pair']}"
        )
    return problems


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def generate(public: Path, root: Path = REPO_ROOT) -> tuple[dict[str, str], dict]:
    """The output files ({relative path: text}) and the validation report."""
    summary = json.loads((public / "summary.json").read_text(encoding="utf-8"))
    workflow = json.loads((public / "workflow.json").read_text(encoding="utf-8"))
    example_tasks = parse_example_tasks(CONFIG_JS.read_text(encoding="utf-8"))
    report: dict[str, Any] = {}
    doc, _rich, _ = build_runs_doc(summary, workflow, report)
    fixture_files = build_fixtures(doc, summary, example_tasks)
    annotate_runs(doc)
    report["n_flagged"] = doc["outliers"]["n_flagged"]
    files = {"runs.json": dumps_runs(doc)}
    files.update({f"fixtures/{k}": v for k, v in fixture_files.items()})
    for name, text in files.items():
        assert_no_leaks(text, name)
    assert_no_private_text(files, root)
    return files, report


def print_report(report: dict) -> None:
    print("Validation (synthetic vs the public aggregates)")
    for topo, r in report["topologies"].items():
        print(
            f"  {TOPOLOGY_LABELS[topo]:<10} n={r['n']}  max |rho err| {r['max_rho_error']:.4f} "
            f"({r['max_rho_pair'][0]} ~ {r['max_rho_pair'][1]})  median err {r['median_error'][0]:.3f} "
            f"({r['median_error'][1]})  IQR err {r['iqr_error'][0]:.3f} ({r['iqr_error'][1]})  "
            f"calibration its {r['iterations']}"
        )
    p = report["pooled"]
    print(
        f"  pooled     n={p['n']}  max |rho err| vs groups.all {p['max_rho_error']:.4f} {p['max_rho_pair']}"
    )
    print(f"  flagged runs: {report['n_flagged']}")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--public", type=Path, default=PUBLIC_DIR, help="public data directory")
    args = ap.parse_args(argv)
    try:
        files, report = generate(args.public)
    except (ValueError, KeyError, LeakError) as exc:
        print(f"error: {exc}")
        return 3 if isinstance(exc, LeakError) else 2
    print_report(report)
    problems = assert_validation(report)
    if problems:
        print("error: validation failed, nothing written:\n  " + "\n  ".join(problems))
        return 1
    for rel, text in files.items():
        path = args.public / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    sizes = {k: len(v.encode()) for k, v in files.items()}
    print(
        f"wrote {len(files)} files to {args.public} (runs.json {sizes['runs.json'] / 1024:.0f} KB)"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
