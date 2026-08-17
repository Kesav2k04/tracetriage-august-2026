"""Out-of-distribution scoring for unseen entities and formats (unit B5).

A cold-entity split guarantees the test set contains stations and transmitters the
model never saw. That is the point of the split, and it is also the condition under
which a confident score is least trustworthy. This module answers, per observation,
"is this unlike anything in training, and on which axis" so the queue can abstain for a
named reason rather than scoring an observation it has no basis for.

Four axes, each a separate signal because they fail differently:

``unseen_station``, ``unseen_transmitter``
    Categorical novelty. Cheap, exact, and the reason a cold split exists.
``unseen_client_family``, ``unseen_band``
    Format novelty. A capture-software family the model never saw renders its axes
    differently, which is a rendering shift rather than a physics one.
``feature_novelty``
    Continuous novelty: Mahalanobis-style distance from the training feature centre,
    computed on the physics block only. The physics block is used because it is
    low-dimensional and has a meaningful covariance; a 16,740-dimensional HOG vector
    has none worth estimating from a few hundred rows.

The categorical signals are deliberately not folded into one score. "Unseen station"
and "geometry unlike anything in training" call for different reviewer notes, and a
single number would collapse them.

The distance threshold is set from the *training* distribution's own quantile, so
"novel" means "further out than 99% of training data", which is a statement about
training rather than a constant someone chose. Unit A7 failed by comparing a
measurement against a hardcoded number, so the quantile is computed and recorded.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np

#: Physics features used for the continuous novelty distance. Deliberately the geometry
#: block: every observation has it (or is degraded, which is itself reported), the
#: dimension is small enough for a covariance estimate, and each axis has physical
#: meaning so a large distance can be explained to a reviewer.
NOVELTY_FEATURES: tuple[str, ...] = (
    "max_elevation_deg",
    "pass_duration_s",
    "doppler_swing_hz",
    "doppler_rate_max_hz_s",
    "tle_epoch_age_days",
)


@dataclass
class OodDetector:
    """Fitted on training rows; scores any row against them."""

    seen_stations: frozenset[Any] = frozenset()
    seen_transmitters: frozenset[str] = frozenset()
    seen_client_families: frozenset[str] = frozenset()
    seen_bands: frozenset[str] = frozenset()
    mean: np.ndarray | None = field(default=None, repr=False)
    inv_cov: np.ndarray | None = field(default=None, repr=False)
    medians: dict[str, float] = field(default_factory=dict)
    distance_quantile_99: float = float("inf")
    n_train: int = 0
    degraded: str | None = None

    def fit(
        self,
        rows: list[dict[str, Any]],
        stations: list[Any],
        transmitters: list[str],
    ) -> OodDetector:
        self.n_train = len(rows)
        self.seen_stations = frozenset(stations)
        self.seen_transmitters = frozenset(transmitters)
        self.seen_client_families = frozenset(
            str(r.get("client_family", "unknown")) for r in rows
        )
        self.seen_bands = frozenset(str(r.get("band", "unknown")) for r in rows)

        x = self._matrix(rows, fit_medians=True)
        if x.shape[0] < len(NOVELTY_FEATURES) * 3:
            self.degraded = "TOO_FEW_TRAIN_ROWS_FOR_COVARIANCE"
            return self

        self.mean = x.mean(axis=0)
        cov = np.cov(x, rowvar=False)
        # Ridge on the diagonal so a near-constant feature cannot make the inverse
        # explode and turn every observation into an outlier. tca_frac is near 0.5 on
        # every pass in this corpus, which is exactly that situation.
        ridge = 1e-6 * np.trace(cov) / max(cov.shape[0], 1)
        self.inv_cov = np.linalg.pinv(cov + ridge * np.eye(cov.shape[0]))

        train_d = self._distance(x)
        self.distance_quantile_99 = float(np.quantile(train_d, 0.99))
        return self

    def _matrix(self, rows: list[dict[str, Any]], fit_medians: bool = False) -> np.ndarray:
        if fit_medians:
            for name in NOVELTY_FEATURES:
                vals = np.array(
                    [_f(r.get(name)) for r in rows], dtype=float
                )
                finite = vals[np.isfinite(vals)]
                self.medians[name] = float(np.median(finite)) if finite.size else 0.0
        cols = []
        for name in NOVELTY_FEATURES:
            v = np.array([_f(r.get(name)) for r in rows], dtype=float)
            cols.append(np.where(np.isfinite(v), v, self.medians.get(name, 0.0)))
        return np.column_stack(cols) if cols else np.zeros((len(rows), 0))

    def _distance(self, x: np.ndarray) -> np.ndarray:
        if self.mean is None or self.inv_cov is None:
            return np.zeros(x.shape[0])
        d = x - self.mean
        return np.sqrt(np.maximum(np.einsum("ij,jk,ik->i", d, self.inv_cov, d), 0.0))

    def score(
        self,
        rows: list[dict[str, Any]],
        stations: list[Any],
        transmitters: list[str],
    ) -> list[dict[str, Any]]:
        x = self._matrix(rows)
        distances = self._distance(x)
        out = []
        for i, r in enumerate(rows):
            unseen_station = stations[i] not in self.seen_stations
            unseen_tx = transmitters[i] not in self.seen_transmitters
            unseen_client = str(r.get("client_family", "unknown")) not in self.seen_client_families
            unseen_band = str(r.get("band", "unknown")) not in self.seen_bands
            far = bool(distances[i] > self.distance_quantile_99)
            axes = [
                name for name, flag in (
                    ("unseen_station", unseen_station),
                    ("unseen_transmitter", unseen_tx),
                    ("unseen_client_family", unseen_client),
                    ("unseen_band", unseen_band),
                    ("feature_novelty", far),
                ) if flag
            ]
            out.append(
                {
                    "obs_id": r.get("obs_id"),
                    "unseen_station": unseen_station,
                    "unseen_transmitter": unseen_tx,
                    "unseen_client_family": unseen_client,
                    "unseen_band": unseen_band,
                    "feature_distance": float(distances[i]),
                    "feature_novelty": far,
                    "novel_axes": axes,
                    "is_ood": bool(axes),
                }
            )
        return out

    def summary(self) -> dict[str, Any]:
        return {
            "n_train": self.n_train,
            "n_seen_stations": len(self.seen_stations),
            "n_seen_transmitters": len(self.seen_transmitters),
            "seen_client_families": sorted(self.seen_client_families),
            "seen_bands": sorted(self.seen_bands),
            "novelty_features": list(NOVELTY_FEATURES),
            "distance_quantile_99": self.distance_quantile_99,
            "degraded": self.degraded,
            "note": (
                "distance_quantile_99 is the 99th percentile of the training set's own "
                "distances, so 'novel' means further out than 99% of training data "
                "rather than past a number chosen by hand."
            ),
        }


def _f(v: Any) -> float:
    if v is None or isinstance(v, bool):
        return float("nan")
    if isinstance(v, (int, float)):
        return float(v)
    return float("nan")


def risk_by_novelty(
    ood_rows: list[dict[str, Any]],
    probs: np.ndarray,
    labels: np.ndarray,
) -> dict[str, Any]:
    """Error rate split by whether each axis flagged the observation.

    This is what makes the OOD score worth having: if the error rate among flagged
    observations is no higher than among unflagged ones, the flag is not detecting
    anything that matters and abstaining on it would cost coverage for nothing. Each
    cell carries its own count, because an error rate over four observations is not a
    rate.
    """
    p = np.asarray(probs, dtype=float)
    y = np.asarray(labels, dtype=int)
    wrong = ((p >= 0.5).astype(int) != y).astype(float)

    out: dict[str, Any] = {}
    for axis in ("unseen_station", "unseen_transmitter", "unseen_client_family",
                 "unseen_band", "feature_novelty", "is_ood"):
        flag = np.array([bool(r[axis]) for r in ood_rows])
        cells = {}
        for label, sel in (("flagged", flag), ("unflagged", ~flag)):
            n = int(sel.sum())
            cells[label] = {
                "n": n,
                "risk": float(wrong[sel].mean()) if n else None,
                "n_errors": int(wrong[sel].sum()) if n else 0,
                "mean_confidence": (
                    float(np.maximum(p[sel], 1 - p[sel]).mean()) if n else None
                ),
            }
        f, u = cells["flagged"]["risk"], cells["unflagged"]["risk"]
        # A null ratio has three different causes and they must not look alike: one of
        # the cells was empty, the denominator was zero errors (the flag separates
        # perfectly, which is the opposite of uninformative), or the ratio is a number.
        if f is None or u is None:
            ratio, ratio_state = None, "one cell was empty"
        elif u == 0.0:
            ratio, ratio_state = None, (
                "undefined: the unflagged cell made no errors, so the flag separates "
                "them completely rather than not at all"
            )
        else:
            ratio, ratio_state = float(f / u), "measured"
        out[axis] = {
            **cells,
            "risk_ratio": ratio,
            "risk_ratio_state": ratio_state,
            "informative": bool(
                f is not None and u is not None and cells["flagged"]["n"] >= 10 and f > u
            ),
        }
    return out
