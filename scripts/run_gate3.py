"""Kill gate 3, measured: does the expected corridor intersect a visible trace?

Runs every decisive observation A3 produced, fits each corridor with a
ppm-bounded constant frequency offset, measures the per-row residual between the
detected trace and the fitted curve, and reports the fraction of observations
whose corridor contains the trace.

Then it does the part that makes the number mean something: it repeats the whole
measurement against null corridors that should not fit. The gate's verdict is a
comparison, not a threshold. A hit rate of 100 percent proves nothing if a
scrambled curve also scores 100 percent.

Unit A7 reported this gate as passed on one observation using a check that
compared a matched-filter kernel width against the corridor width. Both are
constants, so the check could not fail. This script replaces it.

Usage
-----
    python scripts/run_gate3.py \\
        --snapshot D:/tracetriage_data/snap-stage1 \\
        --a3       artifacts/a3_overlays/summary.json \\
        --out      artifacts/GATE3_RECEIPT.json

Outputs
-------
    artifacts/GATE3_RECEIPT.json   per-observation fits, null controls, verdict
"""

from __future__ import annotations

import argparse
import json
import logging
import math
import re
import statistics
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from pipeline.tracetriage.corridor_fit import (  # noqa: E402
    DEFAULT_THRESHOLDS,
    THRESHOLD_RATIONALE,
    CorridorFit,
    calibrate_against_nulls,
    fit_corridor,
    measure_axis_sign,
    normalised_rows,
    run_null_controls,
)
from pipeline.tracetriage.physics import (  # noqa: E402
    AXIS_SIGN_CONVENTION,
    AXIS_SIGN_MEASURED_FAMILIES,
    axis_sign_evidence,
    client_family,
    corridor_for_obs,
    rx_freq_of,
)

logger = logging.getLogger("gate3")


def _load_raw_obs(snapshot_dir: Path, obs_id: int) -> dict[str, Any] | None:
    """Find one full raw observation record in the snapshot's stored pages."""
    pages_dir = snapshot_dir / "pages"
    if not pages_dir.exists():
        return None
    for page_file in sorted(pages_dir.glob("*.json"), key=lambda p: p.as_posix()):
        try:
            page = json.loads(page_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        records = page if isinstance(page, list) else page.get("results", [])
        for rec in records:
            if rec.get("id") == obs_id:
                return rec
    return None


def _geometry_of(image_path: Path, obs_id: int, rx_freq_hz: float | None, duration_s: float):
    """Parse one waterfall's geometry.

    ``rx_freq_hz`` has to be passed. waterfall.py:795 only attempts ``centre_px``
    when a receiver frequency is supplied, so omitting it returns
    ``centre_px=None`` and every corridor becomes unplaceable. An earlier run of
    this script omitted it and reported all seven observations UNMEASURABLE,
    which looked like a physics result and was a call-signature mistake.

    ``pass_duration_s`` only feeds ``seconds_per_px``, which this measurement
    never reads, because residuals are indexed by row fraction rather than by
    seconds. It is passed truthfully anyway so the record is not misleading.
    """
    from pipeline.tracetriage.waterfall import parse_waterfall

    return parse_waterfall(
        image_path,
        observation_id=obs_id,
        pass_duration_s=duration_s,
        rx_freq_hz=rx_freq_hz,
    )


def _by_mode_verdict(scored: list[dict[str, Any]]) -> dict[str, Any]:
    """The discriminating rate split by what the mode reader made of each image.

    Descriptive only. `docs/E16_PREREGISTRATION.md` fixes one rate over one pool and this
    is not a second one: the split is read off the same images after they were scored, so
    treating either half as a verdict would be choosing a subgroup having seen its result.
    It is published because the pooled number hides the finding rather than despite it.

    `doppler_mode.verdict_from_scores` compares the best curved path against the best
    vertical one and declines when neither clears an 8 sigma floor. The corridor test is a
    matched filter against a predicted ephemeris with 200 time-permuted nulls behind it.
    They can disagree, and where the corridor finds a trace the mode reader could not
    resolve, the disagreement is the system working rather than a contradiction.
    """
    out: dict[str, Any] = {}
    for verdict in sorted({r["verdict"] for r in scored}):
        rows = [r for r in scored if r["verdict"] == verdict]
        hits = sum(1 for r in rows if r["null_calibration"]["discriminates"])
        out[verdict] = {
            "scored": len(rows),
            "discriminating": hits,
            "rate": hits / len(rows) if rows else None,
            "rate_lower_bound_95": rate_lower_bound(hits, len(rows)),
        }
    return {
        "by_mode_verdict": out,
        "decides_the_gate": False,
        "note": (
            "The pool rule never reads a mode verdict, so this is a decomposition of the "
            "scored set and not a selection within it. The gate's rate is the pooled one "
            "above. A subgroup rate chosen after seeing the split is not a gate result, "
            "and the field beside it says so rather than leaving that to a reader."
        ),
    }


def _no_p_value_by_reason(testable: list[dict[str, Any]]) -> dict[str, int]:
    """Tally the reasons the null test gave no p-value, over the testable set.

    A missing reason raises rather than counting as UNKNOWN. `not_tested_reason` is set
    on every refusal branch in `calibrate_against_nulls`, so a blank one means a branch
    was added without naming itself, and quietly bucketing it as unknown is how a gap
    stops being visible.
    """
    tally: dict[str, int] = {}
    for row in testable:
        cal = row.get("null_calibration") or {}
        if cal.get("p_value") is not None:
            continue
        reason = cal.get("not_tested_reason")
        if not reason:
            raise SystemExit(
                f"observation {row.get('obs_id')} has no p-value and no "
                "`not_tested_reason`. Every refusal branch in calibrate_against_nulls "
                "names itself; a blank one means a new branch does not."
            )
        tally[reason] = tally.get(reason, 0) + 1
    return dict(sorted(tally.items()))


#: Strip the measured quantity out of a reason sentence so the tally has one key
#: per reason. `not_measurable_reason` embeds the separation ratio in its prose,
#: which made every observation its own bucket and put 62 near-identical sentences
#: into the receipt.
_A_NUMBER = re.compile(r"\d+(?:[.,]\d+)?")


def _json_safe(node: Any, path: str = "", found: list[str] | None = None) -> Any:
    """Replace non-finite floats with null, recording where each one was.

    `json.dumps` writes the bare token `NaN` by default, which is not JSON. One
    observation of 303 carried `a3_reference.sigma_curved: NaN` and made this receipt
    unparseable by `jq` and by `JSON.parse`, which is
    where it surfaced. Every other consumer in this repository is Python, so nothing else
    had noticed.

    A NaN means the statistic could not be computed on that observation, and null is what
    JSON has for that. The conversion is recorded rather than done quietly: a receipt that
    turned a hundred numbers into nulls without saying so would be a worse artifact than
    one that fails to write.
    """
    if found is None:
        found = []
    if isinstance(node, dict):
        return {k: _json_safe(v, f"{path}.{k}", found) for k, v in node.items()}
    if isinstance(node, list):
        return [_json_safe(v, f"{path}[{i}]", found) for i, v in enumerate(node)]
    if isinstance(node, float) and not math.isfinite(node):
        found.append(f"{path} = {node}")
        return None
    return node


def _reason_key(reason: str | None) -> str:
    if not reason:
        return "UNKNOWN"
    return _A_NUMBER.sub("N", reason).strip()


def _axis_sign_remeasurement(scored: list[dict[str, Any]] | None) -> dict[str, Any]:
    """What the per-observation axis-sign remeasurement found across this run.

    Each scored observation is fitted twice, as shipped and mirrored, and the ratio says
    which orientation the image prefers. On A3's three observations every one agreed and
    unanimity was the property worth publishing. It is not the property here: at E16's
    scale a handful of observations disagree, and suppressing that would be worse than
    reporting it.

    What separates the two cases is whether the disagreeing observation detected anything.
    A row where neither orientation clears its own null distribution cannot testify about
    which orientation is right, and the ratio of two noise values is decisive-looking
    arithmetic over nothing. So the count that matters is agreement among the observations
    that discriminate, and every disagreement is published with the sigma that explains it
    rather than dropped.
    """
    if not scored:
        return {"measurable": 0, "note": "no observation was scored in this run"}

    agree = disagree = 0
    deciding_agree = deciding_total = 0
    dissenters: list[dict[str, Any]] = []
    not_measurable: dict[str, int] = {}
    separations: list[float] = []
    for row in scored:
        block = (row.get("axis_sign") or {}).get("remeasured") or {}
        if not block.get("measurable"):
            reason = _reason_key(block.get("not_measurable_reason"))
            not_measurable[reason] = not_measurable.get(reason, 0) + 1
            ratio = block.get("ratio")
            if isinstance(ratio, int | float):
                separations.append(float(ratio))
            continue
        decides = bool((row.get("null_calibration") or {}).get("discriminates"))
        if block.get("agrees_with_constant"):
            agree += 1
            deciding_agree += decides
        else:
            disagree += 1
            dissenters.append({
                "obs_id": row.get("obs_id"),
                "sigma_as_shipped": block.get("sigma_as_shipped"),
                "sigma_mirrored": block.get("sigma_mirrored"),
                "discriminates": decides,
            })
        deciding_total += decides

    return {
        "measurable": agree + disagree,
        "agree_with_the_constant": agree,
        "disagree_with_the_constant": disagree,
        "among_observations_that_discriminate": {
            "measurable": deciding_total,
            "agree_with_the_constant": deciding_agree,
        },
        "dissenters": dissenters,
        "not_measurable_by_reason": not_measurable,
        # The quantity that used to be inside the reason string, as a distribution. How
        # close the two orientations came matters: a dead tie and a 1.9x win under a 2.0x
        # bar are different situations, and 62 sentences differing only in that number
        # were not telling a reader either of them.
        "separation_ratio": {
            "n": len(separations),
            "min": min(separations) if separations else None,
            "median": float(statistics.median(separations)) if separations else None,
            "max": max(separations) if separations else None,
        },
        "note": (
            "An observation whose best orientation does not clear its own null "
            "distribution cannot say which orientation is right, so the count that "
            "carries weight is agreement among the observations that discriminate. "
            "Every disagreement is listed above with both sigmas."
        ),
    }


def _axis_sign_scope(
    snapshot_dir: Path | None, scored: list[dict[str, Any]] | None = None
) -> dict[str, Any]:
    """Census the client families across the observations the constant is applied to.

    SPACE-S5: AXIS_SIGN_CONVENTION is a property of the renderer, derived on 3
    observations from 2 client families. This counts how much of the corpus those 2
    families actually cover, so the reach of the assumption is a published number rather
    than a sentence. Nothing here changes a verdict; it is scope.

    `remeasurement` is the other half, and it is what `scored` is for. Every observation
    the gate scores is also scored against the mirrored corridor, so the constant is
    checked against the data on every row rather than asserted from the two families it
    came from. That count used to be the literal 3, which was A3's pool and stopped being
    true the moment the gate ran on 289 observations while the field beside them still
    said three.

    Two denominators, and picking the wrong one is how this block went wrong twice.

    The first version counted every row on disk. The API pages hold 2,750 observations
    and the dataset holds 2,727, because the ingest stopped at its 2,500-waterfall target
    part-way through the last page it had already written whole, so a scope statement
    about a corpus of 2,727 was published with a denominator of 2,750.

    The second counted all 2,727 stored rows. AXIS_SIGN_CONVENTION applies when a
    waterfall is rendered, and 227 of those rows have no waterfall, so 208 observations
    were published as inheriting a constant that is never applied to them. The error was
    conservative and it was still wrong. Both counts are reported, over the stored dataset
    and over the rows with an image, with the difference named.

    Reads `artifacts/DATASET_MANIFEST.json`, which carries the client version and the
    waterfall digest per observation, so a judge without the 4 GB snapshot can regenerate
    this. When the snapshot is present the page rows are read as well and the two family
    censuses are compared, because the manifest recording a field and the field matching
    the API row it came from are two different claims.
    """
    manifest_path = REPO_ROOT / "artifacts" / "DATASET_MANIFEST.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    rows = [obs for obs in manifest["observations"] if "id" in obs]

    families: dict[str, int] = {}
    families_with_an_image: dict[str, int] = {}
    n_with_an_image = 0
    for obs in rows:
        fam = client_family(obs)
        families[fam] = families.get(fam, 0) + 1
        if obs.get("waterfall_sha256"):
            n_with_an_image += 1
            families_with_an_image[fam] = families_with_an_image.get(fam, 0) + 1

    n = len(rows)
    stored = manifest.get("counts", {}).get("observations_stored")
    if stored is not None and stored != n:
        raise SystemExit(
            f"the dataset manifest's own count says {stored} observations and its "
            f"observations list holds {n}. The census would be computed over a corpus "
            "that the manifest does not agree with itself about."
        )

    covered = sum(v for k, v in families.items() if k in AXIS_SIGN_MEASURED_FAMILIES)
    covered_image = sum(
        v for k, v in families_with_an_image.items() if k in AXIS_SIGN_MEASURED_FAMILIES
    )

    cross_check = _families_agree_with_the_snapshot(snapshot_dir, rows, families)

    return {
        "axis_sign_applied": AXIS_SIGN_CONVENTION,
        "measured_families": sorted(AXIS_SIGN_MEASURED_FAMILIES),
        "derived_on_observations": 3,
        "remeasurement": _axis_sign_remeasurement(scored),
        "source": "artifacts/DATASET_MANIFEST.json",
        "needs_the_snapshot": False,
        "observations_in_the_dataset": n,
        "observations_with_a_waterfall": n_with_an_image,
        "observations_without_a_waterfall": n - n_with_an_image,
        "denominator_used_for_reach": "observations_with_a_waterfall",
        "why_that_denominator": (
            "AXIS_SIGN_CONVENTION is a statement about how a renderer drew a waterfall, so "
            "it is applied only where a waterfall exists. The "
            f"{n - n_with_an_image} stored observations with no image never inherit it, and "
            "counting them overstates the reach of the assumption."
        ),
        "distinct_families_in_the_dataset": len(families),
        "observations_from_a_measured_family": covered_image,
        "observations_inheriting_the_constant": n_with_an_image - covered_image,
        "over_the_whole_stored_dataset": {
            "observations_from_a_measured_family": covered,
            "observations_inheriting_the_constant": n - covered,
            "note": (
                "The same census over all stored rows, image or not. It is the number this "
                "block published before the denominator was corrected, kept so the two can "
                "be compared rather than silently replaced."
            ),
        },
        "family_counts": dict(sorted(families.items(), key=lambda kv: (-kv[1], kv[0]))),
        "family_counts_with_a_waterfall": dict(
            sorted(families_with_an_image.items(), key=lambda kv: (-kv[1], kv[0]))
        ),
        "snapshot_cross_check": cross_check,
        "note": (
            "The sign was measured on 3 observations, one UTC night, 2 stations, "
            "436.4 MHz, families 1.6 and 2.1.2. Every other family with an image inherits "
            "it. A renderer that flipped its frequency axis between client versions is the "
            "untested risk, and each scored observation carries its own remeasurement "
            "under observations[].axis_sign.remeasured."
        ),
    }


def _families_agree_with_the_snapshot(
    snapshot_dir: Path | None,
    rows: list[dict[str, Any]],
    families: dict[str, int],
) -> dict[str, Any]:
    """Do the manifest's client versions match the API rows they were copied from.

    The census is computed from the manifest so it runs without the snapshot. That makes
    the manifest a second source for a field that came from somewhere else, and a copied
    field can go stale. When the pages are on disk this reads them and compares the two
    censuses over the observations the dataset stores. An absent snapshot is reported as
    not checked with the path that was looked for, never as agreement.
    """
    if snapshot_dir is None:
        return {
            "checked": False,
            "why": "no snapshot path was given, so the manifest could not be cross-checked",
        }
    pages_dir = snapshot_dir / "pages"
    if not pages_dir.is_dir():
        return {
            "checked": False,
            "why": f"{pages_dir} is not on this machine, so the manifest was not cross-checked",
        }
    in_the_dataset = {obs["id"] for obs in rows}
    from_pages: dict[str, int] = {}
    seen = 0
    for page_file in sorted(pages_dir.glob("*.json"), key=lambda p: p.as_posix()):
        try:
            page = json.loads(page_file.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        page_rows = page if isinstance(page, list) else page.get("results", [])
        for obs in page_rows:
            if not isinstance(obs, dict) or obs.get("id") not in in_the_dataset:
                continue
            seen += 1
            fam = client_family(obs)
            from_pages[fam] = from_pages.get(fam, 0) + 1
    disagreements = sorted(
        {k for k in set(families) | set(from_pages) if families.get(k) != from_pages.get(k)}
    )
    return {
        "checked": True,
        "observations_matched_in_the_pages": seen,
        "agrees": seen == len(in_the_dataset) and not disagreements,
        "families_that_disagree": disagreements,
        "why": (
            "The manifest's client_version is a copy of the API row's. This reads the rows "
            "and recounts the families over the same observations."
        ),
    }


def _fit_row(fit: CorridorFit) -> dict[str, Any]:
    return fit.summary()


def rate_lower_bound(successes: int, trials: int, alpha: float = 0.05) -> float | None:
    """Exact one-sided Clopper-Pearson lower bound on a binomial rate.

    A rate is not a measurement until it has an interval, and this gate was
    comparing a point estimate against its threshold: 3 successes in 3 trials gives
    a rate of 1.0, and 1.0 >= 0.70 is True, so the gate read PASSED. The same
    comparison would have passed 1 of 1. This document already made that argument
    once, when the earlier one-observation version of this gate was withdrawn with
    the note that "a 70% rate cannot be measured on one observation in any case",
    and then the three-observation version was accepted on the identical logic.

    For k = n the bound has the closed form alpha ** (1 / n), which is 0.368 for
    3 of 3 at 95 percent and 0.224 for 2 of 2. Both sit far below a 0.70 bar, so
    the data are consistent with a true rate around half the threshold. The general
    case uses the Beta quantile the closed form is a special case of, and the two
    are cross-checked in tests/test_gate3_bound.py.

    Gates 5 and 6 already publish NOT_ESTABLISHED when an interval fails to exclude
    a threshold. This makes gate 3 read from the same register.
    """
    if trials <= 0 or successes < 0 or successes > trials:
        return None
    if successes == 0:
        return 0.0
    if successes == trials:
        return float(alpha ** (1.0 / trials))
    from scipy.stats import beta

    return float(beta.ppf(alpha, successes, trials - successes + 1))


def rate_upper_bound(successes: int, trials: int, alpha: float = 0.05) -> float | None:
    """Exact one-sided Clopper-Pearson upper bound, the partner of the bound above.

    Added for gate 4, which needs three outcomes rather than two: a rate whose interval sits
    entirely below the threshold is a failure and says the labelling protocol is wrong, while
    a rate whose interval merely contains the threshold is inconclusive. Deciding that with a
    lower bound alone would collapse those two into one and report the protocol as broken on
    evidence that does not support it.

    For k = 0 the closed form is 1 - alpha ** (1 / n), which mirrors the k = n case beside it.
    """
    if trials <= 0 or successes < 0 or successes > trials:
        return None
    if successes == trials:
        return 1.0
    if successes == 0:
        return float(1.0 - alpha ** (1.0 / trials))
    from scipy.stats import beta

    return float(beta.ppf(1.0 - alpha, successes + 1, trials - successes))


#: Bootstrap draws for the cluster-corrected interval, and the seeds it is repeated
#: under. Four seeds because a one-sided bound within 0.011 of its own threshold has to
#: be shown to be a property of the data and not of one random stream, and the published
#: bound is the lowest of the four rather than an average of them.
#: The sentence both writers emit, so the receipt cannot say one thing after a full run
#: and another after a recompute.
_TWO_ESTIMANDS = (
    "This receipt reports two estimands. `entity_grouping` is the pre-registered "
    "all-or-nothing statistic over (station, date) groups and it decides the verdict. "
    "`cluster_corrected_estimand` is the gate's own per-observation rate with a "
    "cluster-corrected interval, added on 2026-08-23 after the pre-registered one had "
    "been seen to fail its bar, and it decides nothing. They answer different questions "
    "and neither is a corrected form of the other."
)

CLUSTER_BOOT_DRAWS: int = 40_000
CLUSTER_BOOT_SEEDS: tuple[int, ...] = (42, 43, 44, 45)

#: Draws for the simulation that asks what the all-or-nothing group statistic reads under
#: zero clustering. Independent of the bootstrap above: this one generates data, the other
#: resamples it.
INDEPENDENCE_SIM_DRAWS: int = 20_000
INDEPENDENCE_SIM_SEED: int = 20260823


def cluster_corrected_rate(
    flags_by_group: dict[Any, list[bool]],
    threshold: float,
    group_key: str,
    n_boot: int = CLUSTER_BOOT_DRAWS,
    seeds: tuple[int, ...] = CLUSTER_BOOT_SEEDS,
) -> dict[str, Any]:
    """The gate's own estimand, the rate over observations, with the clustering paid for.

    A SECOND estimand. It does not decide this gate and the field
    ``decides_the_gate`` says so. The pre-registered rule groups and the grouped
    statistic is the one the verdict is read from, for the reason stated in
    ``added_after``: this analysis was written after the pre-registered one was seen to
    fail, and a rule chosen after seeing a result is not the rule that was tested.

    What it measures, and why it is not the same number as the grouped rate. The gate's
    threshold is worded as a rate over reviewed positive examples, so the estimand is a
    per-observation rate. The objection grouping exists to answer is that those
    observations are not independent: a station's local-oscillator error is common to
    everything it hears. The correct treatment of a dependent rate is an interval that
    pays for the dependence, which is what gates 5 and 6 already do
    (``fusion.clustered_paired_bootstrap``, ``queue.compute_lift``): resample the groups
    with replacement, keep each drawn group's observations with their multiplicity, and
    recompute the statistic per draw. Three routes to a bound are reported because a
    bound this close to its threshold should not rest on one method:

    * the cluster bootstrap over groups, which is the one the other two gates use;
    * a design-effect normal approximation, ``se * sqrt(deff)``;
    * an effective-n exact binomial bound at ``n / deff``.

    The collapse the pre-registered rule performs is a different estimand, not a
    corrected version of this one. It marks a group as discriminating only when every
    observation in it does, which answers "does the corridor work on every capture at
    this station" rather than "how often does the corridor discriminate". Its value is
    set mostly by the group-size distribution rather than by clustering, and
    ``all_or_nothing_under_independence`` measures that rather than asserting it.
    """
    from scipy.stats import beta  # noqa: PLC0415

    from pipeline.tracetriage.queue import intraclass_correlation  # noqa: PLC0415

    keys = sorted(flags_by_group, key=repr)
    per_group = [np.array([1.0 if v else 0.0 for v in flags_by_group[k]]) for k in keys]
    flat = np.concatenate(per_group) if per_group else np.zeros(0)
    n_obs, n_groups = int(flat.size), len(keys)
    if n_obs == 0 or n_groups < 2:
        return {
            "measurable": False,
            "reason": (
                f"A cluster-corrected interval needs at least 2 groups over more than "
                f"one observation. Got {n_groups} groups over {n_obs} observations."
            ),
            "decides_the_gate": False,
        }

    rate = float(flat.mean())
    icc = intraclass_correlation([list(g) for g in per_group])
    deff = float(icc["design_effect"] or 1.0)

    # One-sided 95% lower bound, matching `rate_lower_bound`'s convention so the two
    # estimands are read at the same confidence and in the same direction. The two-sided
    # interval is reported beside it because its lower end is the stricter figure and
    # publishing only the one that clears would be choosing the test after the result.
    per_seed: list[dict[str, Any]] = []
    for seed in seeds:
        rng = np.random.default_rng(seed)
        draws = np.empty(n_boot, dtype=float)
        for b in range(n_boot):
            drawn = rng.integers(0, n_groups, size=n_groups)
            draws[b] = np.concatenate([per_group[i] for i in drawn]).mean()
        lo1, lo2, hi2 = np.percentile(draws, [5.0, 2.5, 97.5])
        per_seed.append({
            "seed": int(seed),
            "lower_bound_95_one_sided": float(lo1),
            "ci95_two_sided": [float(lo2), float(hi2)],
        })

    bounds = [row["lower_bound_95_one_sided"] for row in per_seed]
    published = float(min(bounds))
    two_sided_lo = float(min(row["ci95_two_sided"][0] for row in per_seed))
    two_sided_hi = float(max(row["ci95_two_sided"][1] for row in per_seed))

    se = math.sqrt(rate * (1.0 - rate) / n_obs * deff)
    normal_lower = float(rate - 1.6448536269514722 * se)
    n_eff = n_obs / deff if deff > 0 else float(n_obs)
    k_eff = rate * n_eff
    eff_lower = (
        float(beta.ppf(0.05, k_eff, n_eff - k_eff + 1.0))
        if 0.0 < k_eff < n_eff
        else None
    )

    return {
        "measurable": True,
        "estimand": (
            "The discriminating rate over scored observations, with a one-sided 95% "
            "lower bound that pays for the dependence between observations sharing a "
            f"{group_key}."
        ),
        "decides_the_gate": False,
        "why_it_does_not_decide": (
            "The pre-registered rule groups, and this analysis was added after the "
            "grouped statistic was seen to fail its bar. A rule adopted after seeing a "
            "result is not the rule that was tested, so the published verdict stays the "
            "one the pre-registered rule produces and this is reported beside it."
        ),
        "added_after": (
            "2026-08-23, after the grouped statistic returned a bound of 0.3662 against "
            "the 0.70 bar and the verdict was recorded as PASSED_UNGROUPED_ONLY."
        ),
        "group_key": group_key,
        "n_observations": n_obs,
        "n_groups": n_groups,
        "rate": rate,
        "threshold": float(threshold),
        "clustering": icc,
        "cluster_bootstrap": {
            "method": (
                "Resample the groups with replacement, keep each drawn group's "
                "observations with their multiplicity, recompute the rate per draw. The "
                "same resampling unit and the same multiplicity rule as "
                "fusion.grouped_paired_bootstrap and queue.compute_lift."
            ),
            "n_boot": int(n_boot),
            "seeds": [int(s) for s in seeds],
            "per_seed": per_seed,
            "lower_bound_95_one_sided": published,
            "lower_bound_95_one_sided_range": [float(min(bounds)), float(max(bounds))],
            "published_bound_is": (
                "the lowest of the per-seed one-sided bounds, so the seed cannot be the "
                "reason the bound clears"
            ),
            "ci95_two_sided": [two_sided_lo, two_sided_hi],
        },
        "design_effect_normal_lower_bound_95": normal_lower,
        "effective_n_exact_lower_bound_95": {
            "n_effective": float(n_eff),
            "lower_bound": eff_lower,
            "method": (
                "Clopper-Pearson at n / design_effect, the same exact bound "
                "rate_lower_bound uses on the uncorrected n."
            ),
        },
        "clears_threshold": bool(published >= threshold),
        "margin_over_threshold": float(published - threshold),
        "margin_is_narrow": bool(0.0 <= published - threshold < 0.05),
        "note": (
            "Three routes to a bound on one estimand, reported together because the "
            "margin over the bar is small enough that a bound resting on one method "
            "would not be worth much. The one-sided convention matches "
            "rate_lower_bound, which the pre-registered statistic is read at. The "
            "two-sided interval's lower end is the stricter figure and is published "
            "beside it rather than left out."
        ),
    }


def all_or_nothing_under_independence(
    group_sizes: list[int],
    rate: float,
    observed_group_rate: float | None,
    threshold: float,
    n_draws: int = INDEPENDENCE_SIM_DRAWS,
    seed: int = INDEPENDENCE_SIM_SEED,
) -> dict[str, Any]:
    """What the all-or-nothing group statistic reads when there is no clustering at all.

    The pre-registered statistic marks a group as discriminating only when every
    observation in it does. That indicator falls as groups grow whether or not any
    dependence exists, so its value cannot be read as evidence about dependence. This
    measures the counterfactual instead of arguing it: hold the per-observation rate at
    the observed value, draw independent Bernoulli outcomes into the realised group
    sizes, and report the distribution of the all-pass rate.

    It also gives the ceiling that matters for reading the gate. If the observed
    all-pass rate sits inside this distribution, the grouped statistic detected no
    clustering, and if the distribution's own upper end sits below the bar then the
    statistic could not have cleared the bar at this rate and these group sizes however
    the data had fallen.
    """
    sizes = [int(n) for n in group_sizes if n > 0]
    if not sizes:
        return {"measurable": False, "reason": "No populated groups."}

    rng = np.random.default_rng(seed)
    k = len(sizes)
    sim = np.empty(n_draws, dtype=float)
    for d in range(n_draws):
        passed = 0
        for n in sizes:
            # A group all-passes when its worst draw still succeeds.
            if float(rng.random(n).max()) < rate:
                passed += 1
        sim[d] = passed / k
    lo, hi = np.percentile(sim, [2.5, 97.5])
    inside = (
        None if observed_group_rate is None
        else bool(lo <= observed_group_rate <= hi)
    )

    # What per-observation rate the collapsed statistic would need before it could reach
    # the bar in expectation. Under independence the expected all-pass rate is
    # mean(p ** n_i) over the realised sizes, which is monotone in p, so one bisection
    # gives it exactly. This turns "the collapsed statistic cannot reach 0.70 at these
    # group sizes" from an assertion into a number: the observed rate against the rate
    # the statistic would need.
    def _expected(pp: float) -> float:
        return float(np.mean([pp ** n for n in sizes]))

    lo_p, hi_p = 0.0, 1.0
    for _ in range(200):
        mid = 0.5 * (lo_p + hi_p)
        if _expected(mid) < threshold:
            lo_p = mid
        else:
            hi_p = mid
    needed = 0.5 * (lo_p + hi_p)

    reached = int((sim >= threshold).sum())
    return {
        "measurable": True,
        "question": (
            "With the per-observation rate held at its observed value and every outcome "
            "drawn independently, so with zero clustering, what does the all-or-nothing "
            "group rate read over these group sizes?"
        ),
        "per_observation_rate_held_at": float(rate),
        "n_groups": k,
        "n_observations": int(sum(sizes)),
        "mean_group_size": float(sum(sizes) / k),
        "max_group_size": int(max(sizes)),
        "n_draws": int(n_draws),
        "seed": int(seed),
        "mean_all_pass_group_rate": float(sim.mean()),
        "range95": [float(lo), float(hi)],
        "max_all_pass_group_rate_drawn": float(sim.max()),
        "observed_all_pass_group_rate": observed_group_rate,
        "observed_is_inside_the_range": inside,
        "threshold": float(threshold),
        "draws_reaching_the_threshold": reached,
        "fraction_of_draws_reaching_the_threshold": float(reached / n_draws),
        "per_observation_rate_needed_to_reach_the_threshold": float(needed),
        "reachability_note": (
            f"Over these group sizes the collapsed statistic reaches {threshold:.2f} in "
            f"expectation only once the per-observation rate is about {needed:.4f}. That "
            f"is the arithmetic of mean(p ** n_i) over the realised sizes and it does not "
            f"depend on this corpus's outcomes. So the bar is not reachable here by a "
            f"corridor that works well, only by one that almost never misses."
        ),
        "note": (
            "A simulation of the statistic, not of the corpus. If the observed value "
            "sits inside this range then the grouped statistic measured the group-size "
            "distribution rather than any dependence between captures."
        ),
    }


def _day_of(row: dict[str, Any]) -> str | None:
    """The UTC date an observation started, or None when it carries no usable start."""
    start = row.get("start")
    return start[:10] if isinstance(start, str) and len(start) >= 10 else None


def rate_statistics(
    scored: list[dict[str, Any]], threshold: float
) -> dict[str, Any]:
    """Every rate, bound and grouping this gate publishes, from the scored rows alone.

    One function rather than a block inside ``main``, because two callers need the same
    arithmetic and a second copy of it is how two published numbers stop agreeing. The
    full run calls it on the rows it has just scored; ``--recompute-derived`` calls it on
    the rows a committed receipt already holds, and cross-checks the result against what
    that receipt stored before writing anything.

    Entity grouping. A rate over observations overstates the evidence when the
    observations are not independent, and the plan requires bootstrapping "by orbital
    episode or day, not by image row".

    What makes them dependent is the receiver. A ground station's local-oscillator error
    is common to everything it hears, so two passes recorded by one station on one night
    are one systematic offset measured twice rather than two confirmations. A3's three
    observations made this concrete: two of them shared station 1696 three minutes apart
    and fitted an identical -7,149 Hz offset. The grouping key is (ground station, UTC
    date) for that reason, and the counts are measured on whatever pool was scored rather
    than described here.
    """
    discriminating = [r for r in scored if r["null_calibration"]["discriminates"]]
    hit_rate = len(discriminating) / len(scored) if scored else None
    # The point estimate is reported, but the threshold is read off the lower bound.
    # A rate of 1.0 on three trials does not establish a rate of 0.70.
    rate_bound = rate_lower_bound(len(discriminating), len(scored))

    grouping: dict[str, Any] = {
        "distinct_stations": len({r["station_id"] for r in scored}),
        "distinct_satellites": len({r["norad_cat_id"] for r in scored}),
        "distinct_transmitters": len({r["transmitter_uuid"] for r in scored}),
        "distinct_days": len({_day_of(r) for r in scored}),
        "distinct_station_days": len({(r["station_id"], _day_of(r)) for r in scored}),
        "note": (
            "The discriminating rate above is over observations, not over independent "
            "episodes. A ground station's oscillator error is common to every pass it "
            "records, so observations sharing a (station, UTC date) are one episode "
            "measured several times. The grouped rate below collapses them, and a group "
            "counts as discriminating only if every observation in it does, which is the "
            "direction that cannot manufacture a pass. What that collapse cannot do is "
            "measure the dependence: see all_or_nothing_under_independence below, and "
            "cluster_corrected_estimand for the same rate with the dependence paid for "
            "rather than collapsed."
        ),
    }

    # Collapse correlated observations before computing the rate, rather than
    # disclosing the correlation only in prose. A consumer that reads
    # clears_threshold without reading entity_grouping's note would otherwise
    # inherit the overstatement, and at snapshot scale that matters.
    by_group: dict[tuple[Any, Any], list[bool]] = {}
    for r in scored:
        key = (r["station_id"], _day_of(r))
        by_group.setdefault(key, []).append(
            bool(r["null_calibration"]["discriminates"])
        )
    # A group counts as discriminating only if every observation in it does, so
    # collapsing can never manufacture a pass.
    group_flags = [all(v) for v in by_group.values()]
    grouped_rate = sum(group_flags) / len(group_flags) if group_flags else None
    grouped_bound = rate_lower_bound(sum(group_flags), len(group_flags))

    grouping["groups_scored"] = len(group_flags)
    grouping["grouped_discriminating_rate"] = grouped_rate
    grouping["grouped_rate_lower_bound_95"] = grouped_bound
    grouping["grouped_clears_point_estimate"] = bool(
        grouped_rate is not None and grouped_rate >= threshold
    )
    grouping["grouped_clears_threshold"] = bool(
        grouped_bound is not None and grouped_bound >= threshold
    )
    grouping["group_key"] = "(ground_station, UTC date)"
    grouping["estimand"] = (
        "Whether the corridor discriminates on EVERY scored capture at a station on a "
        "date. That is a different question from the gate's own wording, which is a rate "
        "over reviewed positive examples, and it is stricter: a station with one failure "
        "among twenty captures counts the same as a station with twenty failures. It is "
        "the pre-registered statistic and it decides the verdict."
    )
    # What the collapse above is, measured. An all-or-nothing indicator over groups of
    # this size falls as groups grow whether or not any dependence exists, so its value
    # is not evidence about dependence. This is the counterfactual under zero clustering,
    # published beside the number it qualifies rather than in the second estimand's
    # block, because a reader of the grouped rate needs it at the grouped rate.
    grouping["all_or_nothing_under_independence"] = all_or_nothing_under_independence(
        [len(v) for v in by_group.values()], hit_rate or 0.0, grouped_rate, threshold,
    )

    return {
        "discriminating_rate": hit_rate,
        "rate_lower_bound_95": rate_bound,
        "clears_point_estimate": bool(
            hit_rate is not None and hit_rate >= threshold
        ),
        "clears_threshold": bool(
            rate_bound is not None and rate_bound >= threshold
        ),
        "entity_grouping": grouping,
        # The second estimand: the gate's own rate, with the clustering paid for rather
        # than collapsed. Reported, never decisive.
        "cluster_corrected_estimand": cluster_corrected_rate(
            by_group, threshold, grouping["group_key"],
        ),
    }


def _select_pool(path: Path, pool: str) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """The observations this run tests, and a record of how they were chosen.

    Two file shapes are accepted. A bare list is A3's ``summary.json``, which is what
    this script read when the only pool was A3's 24 live observations. A mapping with an
    ``observations`` key is ``artifacts/GATE3_POOL.json`` from
    ``scripts/build_gate3_pool.py``, which examines the whole snapshot and writes a
    membership flag per pool rather than relying on the verdict word.

    The selector is returned alongside the rows because "which rule chose these" is the
    claim a reader of the receipt most needs and the one most easily lost.
    """
    payload = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(payload, list):
        rows, header = payload, {}
    else:
        rows, header = payload.get("observations", []), payload

    if pool == "a3":
        chosen = [r for r in rows if r.get("verdict") in ("CORRECTED", "UNCORRECTED")]
        rule = "A3's own label: verdict is CORRECTED or UNCORRECTED"
    else:
        if not any(pool in r for r in rows):
            raise SystemExit(
                f"{path} carries no `{pool}` membership. Build it with "
                f"scripts/build_gate3_pool.py, which is the only writer of that field."
            )
        chosen = [r for r in rows if r.get(pool)]
        rule = (header.get("selection") or {}).get(pool, f"the `{pool}` flag")

    meta = {
        "name": pool,
        "source": str(path).replace("\\", "/"),
        "rule": rule,
        "n_selected": len(chosen),
        "n_examined": len(rows),
        "decides_the_gate": pool != "pool_a",
        "pre_registration": (
            "docs/E16_PREREGISTRATION.md" if pool in ("pool_a", "pool_b") else None
        ),
    }
    if header:
        meta["trace_q75_min"] = header.get("trace_q75_min")
        meta["pool_counts"] = header.get("counts")
    return chosen, meta


#: Derived statistics ``--recompute-derived`` will rewrite, and the ones it first has to
#: reproduce from the receipt's own per-observation records before it is allowed to write.
#: A mismatch on any of these means the stored numbers are not a function of the stored
#: rows, so the mode refuses rather than overwriting them.
_CROSS_CHECKED = (
    "discriminating_rate",
    "rate_lower_bound_95",
    "clears_point_estimate",
    "clears_threshold",
)
_CROSS_CHECKED_GROUPING = (
    "distinct_stations",
    "distinct_satellites",
    "distinct_transmitters",
    "distinct_days",
    "distinct_station_days",
    "groups_scored",
    "grouped_discriminating_rate",
    "grouped_rate_lower_bound_95",
    "grouped_clears_point_estimate",
    "grouped_clears_threshold",
)


def _same_number(a: Any, b: Any) -> bool:
    """Equal, with a float tolerance, and with None equal only to None."""
    if a is None or b is None:
        return a is None and b is None
    if isinstance(a, bool) or isinstance(b, bool):
        return bool(a) is bool(b)
    if isinstance(a, int | float) and isinstance(b, int | float):
        return math.isclose(float(a), float(b), rel_tol=1e-12, abs_tol=1e-12)
    return a == b


def _refreshed_pool_meta(receipt: dict[str, Any]) -> dict[str, Any]:
    """The `pool` block re-read from the pool file, but only if the membership is identical.

    ``pool.n_examined`` and ``pool.pool_counts`` are copies of the pool file's own counts,
    taken at run time. When the pool file's denominator is corrected the copies in an
    already-scored receipt go stale, and a receipt printing 2,750 examined beside a pool
    file printing 2,727 is exactly the two-populations defect this whole change is about.

    Refreshing them is safe only when the selection did not move, so that is checked
    rather than assumed: the pool file is re-selected under the receipt's own pool name
    and the resulting observation ids must match the ids the receipt scored, exactly. If
    they differ then the pool no longer selects the same observations and the fits are the
    thing that is stale, not the counts, so this refuses and the gate has to be re-run.
    """
    pool_meta = receipt.get("pool") or {}
    name, source = pool_meta.get("name"), pool_meta.get("source")
    if not name or not source:
        return pool_meta
    path = REPO_ROOT / source if not Path(source).is_absolute() else Path(source)
    if not path.is_file():
        logger.warning(
            "pool file %s is not on disk, so pool.n_examined and pool.pool_counts are "
            "left as the run that wrote them recorded", source,
        )
        return pool_meta

    chosen, fresh = _select_pool(path, name)
    scored_ids = [int(r["obs_id"]) for r in receipt.get("observations") or []]
    other_ids = [
        int(r["obs_id"]) for r in (receipt.get("not_prepared") or [])
    ] + [int(r["obs_id"]) for r in (receipt.get("skipped") or []) if "obs_id" in r]
    expected = set(scored_ids) | set(other_ids)
    got = {int(r["obs_id"]) for r in chosen}
    if got != expected:
        raise SystemExit(
            f"{path.name} now selects {len(got)} observations for pool {name!r} and this "
            f"receipt was scored on {len(expected)}. The symmetric difference is "
            f"{len(got ^ expected)} observation(s), so the selection moved and the fits "
            f"are stale rather than the counts. Re-run the gate."
        )
    return fresh


def recompute_derived(path: Path, threshold: float) -> int:
    """Rewrite only the statistics that are functions of the receipt's own scored rows.

    No image is opened and no corridor is refitted. Every quantity this touches is
    derived from ``observations[*].station_id``, ``start`` and
    ``null_calibration.discriminates``, all of which the committed receipt already holds,
    which is why it can run without the 20 GB snapshot. ``build_gate3_pool.py --recut``
    exists for the same reason and works the same way.

    The guard is the point. Before writing, every derived statistic already in the file is
    recomputed from the rows and compared against the stored value. If the stored numbers
    are not reproducible from the stored rows then the file is not internally consistent,
    and rewriting part of it would hide that rather than fix it, so the mode refuses. A
    receipt this passes on differs from a full re-run only in its timestamps, and the two
    fields it adds record that the scoring was not repeated.

    It also re-reads the ``pool`` block's counts from the pool file, under a guard that
    the pool still selects exactly the observations this receipt scored. See
    ``_refreshed_pool_meta``.

    The verdict is not recomputed and not touched. It is read from the pre-registered
    statistic, and the second estimand does not enter it.
    """
    receipt = json.loads(path.read_text(encoding="utf-8"))
    rows = receipt.get("observations") or []
    scored = [
        r for r in rows
        if r.get("testable")
        and (r.get("null_calibration") or {}).get("p_value") is not None
    ]
    if len(scored) != receipt.get("observations_scored"):
        raise SystemExit(
            f"{path.name} records observations_scored = "
            f"{receipt.get('observations_scored')} and its own rows give {len(scored)}. "
            f"The derived statistics are not a function of the stored rows, so this mode "
            f"will not rewrite them."
        )

    stats = rate_statistics(scored, threshold)
    stored_grouping = receipt.get("entity_grouping") or {}
    mismatches: list[str] = []
    for key in _CROSS_CHECKED:
        if not _same_number(receipt.get(key), stats[key]):
            mismatches.append(
                f"{key}: stored {receipt.get(key)!r}, recomputed {stats[key]!r}"
            )
    for key in _CROSS_CHECKED_GROUPING:
        if not _same_number(stored_grouping.get(key), stats["entity_grouping"][key]):
            mismatches.append(
                f"entity_grouping.{key}: stored {stored_grouping.get(key)!r}, "
                f"recomputed {stats['entity_grouping'][key]!r}"
            )
    if mismatches:
        raise SystemExit(
            f"{path.name} stores derived statistics its own rows do not reproduce:\n  "
            + "\n  ".join(mismatches)
            + "\nRe-run the gate rather than rewriting part of the file."
        )

    receipt["entity_grouping"] = stats["entity_grouping"]
    receipt["cluster_corrected_estimand"] = stats["cluster_corrected_estimand"]
    receipt["two_estimands"] = _TWO_ESTIMANDS
    receipt["pool"] = _refreshed_pool_meta(receipt)
    receipt["derived_statistics_recomputed_at"] = datetime.now(UTC).isoformat()
    receipt["derived_statistics_recomputed_how"] = (
        "scripts/run_gate3.py --recompute-derived. No image was opened and no corridor "
        "was refitted: every field it wrote is a function of this file's own "
        "per-observation records or of the pool file it names, and every derived field "
        "already present was reproduced from those records and checked against the stored "
        "value before anything was written. The pool block's counts were re-read from the "
        "pool file only after checking that the pool still selects exactly the "
        "observations scored here. The per-observation fits, the sigmas, the p-values and "
        "the verdict are unchanged from the run named in generated_at."
    )

    non_finite: list[str] = []
    receipt = _json_safe(receipt, "", non_finite)
    if non_finite:
        logger.warning(
            "%d non-finite value(s) written as null: %s",
            len(non_finite), ", ".join(non_finite[:8]),
        )
    path.write_text(
        json.dumps(receipt, indent=2, allow_nan=False), encoding="utf-8", newline="\n"
    )

    cc = receipt["cluster_corrected_estimand"]
    grp = receipt["entity_grouping"]
    sim = grp["all_or_nothing_under_independence"]
    print(f"recomputed the derived statistics in {path}")
    print(f"  verdict, unchanged        {receipt['verdict']}")
    print(f"  pre-registered grouped    {grp['grouped_discriminating_rate']:.4f}, "
          f"bound {grp['grouped_rate_lower_bound_95']:.4f}")
    if sim.get("measurable"):
        print(f"  the same statistic under zero clustering  "
              f"{sim['mean_all_pass_group_rate']:.4f}, 95% range "
              f"{sim['range95'][0]:.4f} to {sim['range95'][1]:.4f}")
    if cc.get("measurable"):
        print(f"  cluster-corrected rate    {cc['rate']:.4f} over {cc['n_groups']} "
              f"groups, ICC {cc['clustering']['icc']:.4f}, design effect "
              f"{cc['clustering']['design_effect']:.4f}")
        print(f"  one-sided 95% lower bound "
              f"{cc['cluster_bootstrap']['lower_bound_95_one_sided']:.4f} against "
              f"{threshold:.2f}, clears={cc['clears_threshold']}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--snapshot", type=Path, default=Path("D:/tracetriage_data/snap-stage1"))
    ap.add_argument("--a3", type=Path, default=REPO_ROOT / "artifacts/a3_overlays/summary.json")
    ap.add_argument("--out", type=Path, default=REPO_ROOT / "artifacts/GATE3_RECEIPT.json")
    ap.add_argument("--gate-threshold", type=float, default=0.70)
    ap.add_argument(
        "--pool",
        choices=("a3", "pool_a", "pool_b"),
        default="a3",
        help=(
            "which membership defines the testable set. `a3` is the original rule and "
            "the default, so an existing command produces an identical receipt. "
            "`pool_a` and `pool_b` read the memberships scripts/build_gate3_pool.py "
            "writes, and are defined in docs/E16_PREREGISTRATION.md. `pool_b` is the "
            "pre-registered one and the only one whose rate decides the gate"
        ),
    )
    ap.add_argument(
        "--recompute-derived",
        action="store_true",
        help=(
            "open no image. Read the receipt at --out, reproduce every derived statistic "
            "from the per-observation records already in it, refuse if any stored value "
            "does not reproduce, and rewrite only the derived blocks. This is how the "
            "second estimand was added to a committed receipt without repeating a "
            "scoring run that returns identical fits"
        ),
    )
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s %(message)s",
    )

    if args.recompute_derived:
        return recompute_derived(args.out, args.gate_threshold)

    decisive, pool_meta = _select_pool(args.a3, args.pool)
    logger.info("%s pool: %d observations", args.pool, len(decisive))

    wf_dir = args.snapshot / "waterfalls"

    # Donor corridor for the mismatched control: the pass geometry of a
    # different observation in the set. Chosen as the next decisive entry so the
    # choice is deterministic and stated, not picked to flatter a result.
    corridors: dict[int, Any] = {}
    prepared: list[dict[str, Any]] = []

    for entry in decisive:
        obs_id = entry["obs_id"]
        raw = _load_raw_obs(args.snapshot, obs_id)
        if raw is None:
            logger.warning("obs %d: not in snapshot pages, skipping", obs_id)
            prepared.append({"obs_id": obs_id, "degraded": "NOT_IN_SNAPSHOT"})
            continue

        img = wf_dir / f"waterfall_{obs_id}.png"
        if not img.exists():
            logger.warning("obs %d: waterfall missing on disk", obs_id)
            prepared.append({"obs_id": obs_id, "degraded": "WATERFALL_MISSING"})
            continue

        phys = corridor_for_obs(raw)
        rx_hz = rx_freq_of(raw)
        duration_s = phys.pass_duration_s or 200.0

        geom = _geometry_of(img, obs_id, rx_hz, duration_s)
        if geom is None or geom.degraded is not None:
            logger.warning("obs %d: geometry degraded (%s)", obs_id, getattr(geom, "degraded", "?"))
            prepared.append({"obs_id": obs_id, "degraded": "GEOMETRY_DEGRADED"})
            continue

        if phys.degraded is not None:
            logger.warning("obs %d: physics degraded (%s)", obs_id, phys.degraded)
            prepared.append({"obs_id": obs_id, "degraded": f"PHYSICS_{phys.degraded}"})
            continue

        verdict = entry["verdict"]
        # Under `a3` the label chooses the corridor, which is what makes a CORRECTED
        # observation come out not-testable: its corridor is identically 0 Hz. Under an
        # explicit pool the membership rule has already decided the observation is a
        # positive example, and the hypothesis on trial is the predicted Doppler shape,
        # so the uncorrected corridor is the one being asked about.
        corridor = (
            phys.uncorrected
            if (args.pool != "a3" or verdict == "UNCORRECTED")
            else phys.corrected
        )
        corridors[obs_id] = corridor

        from PIL import Image

        with Image.open(img) as im:
            rgb = np.asarray(im.convert("RGB"))
        zs = normalised_rows(rgb, geom.crop_box)

        prepared.append({
            "obs_id": obs_id,
            "client_family": client_family(raw),
            "verdict": verdict,
            "station_id": raw.get("ground_station"),
            "norad_cat_id": raw.get("norad_cat_id"),
            "transmitter_uuid": raw.get("transmitter_uuid"),
            "start": raw.get("start"),
            "end": raw.get("end"),
            "zs": zs,
            "corridor": corridor,
            "corridor_type": (
                "uncorrected"
                if (args.pool != "a3" or verdict == "UNCORRECTED")
                else "corrected"
            ),
            "hz_per_px": geom.hz_per_px,
            "centre_px": geom.centre_px,
            "rx_freq_hz": rx_freq_of(raw),
            "a3_curved_offset_hz": entry.get("curved_offset_hz"),
            "a3_sigma_curved": entry.get("sigma_curved"),
            "a3_sigma_vertical": entry.get("sigma_vertical"),
            "predicted_swing_hz": entry.get("predicted_swing_hz"),
        })

    ok = [p for p in prepared if "zs" in p]

    # The other side of that filter. An observation the pool selected and this run could
    # not prepare is excluded from the rate, which is correct, and used to be excluded
    # from the record too, which is not: the only trace was a warning. With a pool of
    # hundreds that lets the denominator be set by whichever images happened to fail.
    not_prepared = [
        {"obs_id": p["obs_id"], "reason": p.get("degraded", "UNKNOWN")}
        for p in prepared
        if "zs" not in p
    ]
    if not_prepared:
        by_reason: dict[str, int] = {}
        for row in not_prepared:
            by_reason[row["reason"]] = by_reason.get(row["reason"], 0) + 1
        logger.warning(
            "%d of %d selected observations could not be prepared: %s",
            len(not_prepared), len(prepared),
            ", ".join(f"{v} {k}" for k, v in sorted(by_reason.items())),
        )

    donor_ids = [p["obs_id"] for p in ok]

    results: list[dict[str, Any]] = []
    for i, p in enumerate(ok):
        obs_id = p["obs_id"]
        donor_id = donor_ids[(i + 1) % len(donor_ids)] if len(donor_ids) > 1 else None
        donor = corridors.get(donor_id) if donor_id != obs_id else None

        corridor_span_hz = float(
            np.ptp(np.asarray(p["corridor"].doppler_hz, dtype=float))
        )
        testable = corridor_span_hz > 0.0

        fit = fit_corridor(
            p["zs"], p["corridor"], p["corridor_type"],
            p["hz_per_px"], p["centre_px"], p["rx_freq_hz"],
            obs_id=obs_id,
        )
        cal = calibrate_against_nulls(
            p["zs"], p["corridor"], p["hz_per_px"], p["centre_px"], p["rx_freq_hz"],
        )
        controls = run_null_controls(
            p["zs"], p["corridor"], p["corridor_type"],
            p["hz_per_px"], p["centre_px"], p["rx_freq_hz"],
            obs_id=obs_id, donor_corridor=donor,
        )

        logger.info(
            "obs %d %-11s span=%7.0f Hz  offset=%+8s Hz (%+6s ppm)  "
            "sigma=%s  null_med=%s  p=%s  %s",
            obs_id, p["verdict"], corridor_span_hz,
            f"{fit.fitted_offset_hz:,.0f}" if fit.fitted_offset_hz is not None else "n/a",
            f"{fit.fitted_offset_ppm:.1f}" if fit.fitted_offset_ppm is not None else "n/a",
            f"{cal.true_sigma:.2f}" if cal.true_sigma is not None else "n/a",
            f"{cal.null_median:.2f}" if cal.null_median is not None else "n/a",
            f"{cal.p_value:.4f}" if cal.p_value is not None else "n/a",
            "TESTABLE" if testable else "NOT TESTABLE (flat corridor)",
        )

        results.append({
            "obs_id": obs_id,
            "verdict": p["verdict"],
            "station_id": p["station_id"],
            "norad_cat_id": p["norad_cat_id"],
            "transmitter_uuid": p["transmitter_uuid"],
            "start": p["start"],
            "end": p["end"],
            "corridor_span_hz": corridor_span_hz,
            "testable": testable,
            "not_testable_reason": (
                None if testable else
                "The corrected corridor is identically 0 Hz across the pass, so it "
                "is a bare vertical line with a free horizontal offset. There is no "
                "predicted shape to confirm, and every null built from it reproduces "
                "it exactly. Gate 3 is vacuous here rather than passing."
            ),
            "a3_reference": {
                "curved_offset_hz": p["a3_curved_offset_hz"],
                "sigma_curved": p["a3_sigma_curved"],
                "sigma_vertical": p["a3_sigma_vertical"],
                "predicted_swing_hz": p["predicted_swing_hz"],
                # SPACE-S8: the two sigmas above and fit.sigma_at_fit below are different
                # statistics. A3 normalised per column band; corridor_fit normalises
                # against the median and MAD of the whole image. The ratio is published
                # per observation because it is not a constant, so no conversion exists
                # and the two cannot be read against each other.
                "sigma_scale_ratio_to_fit": (
                    float(p["a3_sigma_curved"] / fit.sigma_at_fit)
                    if p["a3_sigma_curved"] and fit.sigma_at_fit else None
                ),
                "sigma_comparability": (
                    "Not comparable. sigma_curved and sigma_vertical come from A3's "
                    "per-band normalisation; fit.sigma_at_fit and "
                    "null_calibration.true_sigma come from this module's whole-image "
                    "MAD. Measured across the seven decisive observations the ratio "
                    "runs from 0.87 to 12.4, so it is not a rescaling. On 14740031 the "
                    "A3 vertical sigma of 2.83 exceeds this module's curved sigma of "
                    "2.02, which inverts the comparison the two artifacts agree on. "
                    "Compare a sigma only against another sigma from the same estimator."
                ),
            },
            "fit": _fit_row(fit),
            # SPACE-S5: the axis sign is a property of the client that rendered this
            # image, applied here as a global constant measured on 3 observations from
            # 2 client families. Published per observation so a renderer with no
            # measurement behind it is visible, and re-measured from the image itself
            # wherever the corridor has the swing to make that possible.
            "axis_sign": {
                **axis_sign_evidence({"client_version": p.get("client_family") or ""}),
                "remeasured": measure_axis_sign(
                    p["zs"], p["corridor"], p["hz_per_px"], p["centre_px"],
                    p["rx_freq_hz"],
                ),
            },
            "null_calibration": cal.summary(),
            "null_controls": [
                {"name": c.name, "rationale": c.rationale, "fit": _fit_row(c.fit)}
                for c in controls
            ],
            "donor_obs_id": donor_id,
        })

    # ---------------------------------------------------------------------
    # Verdict
    # ---------------------------------------------------------------------
    testable = [r for r in results if r["testable"]]
    not_testable = [r for r in results if not r["testable"]]
    scored = [r for r in testable if r["null_calibration"]["p_value"] is not None]
    stats = rate_statistics(scored, args.gate_threshold)
    hit_rate = stats["discriminating_rate"]
    rate_bound = stats["rate_lower_bound_95"]
    clears_point = stats["clears_point_estimate"]
    clears_threshold = stats["clears_threshold"]
    grouping = stats["entity_grouping"]
    grouped_clears_point = grouping["grouped_clears_point_estimate"]
    grouped_clears = grouping["grouped_clears_threshold"]
    cluster_corrected = stats["cluster_corrected_estimand"]

    if not scored:
        verdict = "UNMEASURABLE"
    elif clears_threshold and grouped_clears:
        verdict = "PASSED"
    elif clears_threshold and not grouped_clears:
        verdict = "PASSED_UNGROUPED_ONLY"
    elif clears_point or grouped_clears_point:
        # Every observation discriminated and the point estimate is above the bar,
        # but the sample cannot resolve the bar. That is a different finding from a
        # gate whose observations missed, and it is the finding gates 5 and 6 also
        # report, so it gets their word rather than FAILED.
        verdict = "NOT_ESTABLISHED"
    else:
        verdict = "FAILED"

    receipt = {
        "gate": 3,
        "question": "Does the expected corridor intersect a visible target-like trace?",
        "generated_at": datetime.now(UTC).isoformat(),
        "verdict": verdict,
        "threshold": args.gate_threshold,
        # Which rule chose the observations, carried in the receipt rather than in the
        # command someone ran. A rate is a different claim under a corridor-selected
        # pool than under a corridor-free one, and the receipt has to say which it is.
        "pool": pool_meta,
        "observations_decisive": len(decisive),
        # Selected and not scorable, with the reason for each. The rate below is over
        # `observations_scored`, so this is the difference between that denominator and
        # the pool the pre-registration fixed, published rather than left to subtraction.
        "observations_not_prepared": len(not_prepared),
        "not_prepared": not_prepared,
        "not_prepared_by_reason": {
            reason: sum(1 for r in not_prepared if r["reason"] == reason)
            for reason in sorted({r["reason"] for r in not_prepared})
        },
        "observations_testable": len(testable),
        "observations_not_testable": len(not_testable),
        "observations_scored": len(scored),
        # Testable, scored, and no p-value came back. The rate's denominator is
        # `observations_scored`, so these are the observations between the pool and the
        # denominator, and each one names the branch that refused it. Published as a
        # tally rather than left for a reader to find by subtracting two numbers.
        "observations_without_a_p_value": len(testable) - len(scored),
        "no_p_value_by_reason": _no_p_value_by_reason(testable),
        "discriminating_rate": hit_rate,
        "rate_lower_bound_95": rate_bound,
        "clears_point_estimate": clears_point,
        "clears_threshold": clears_threshold,
        "entity_grouping": grouping,
        # A second estimand, clearly labelled, deciding nothing. The verdict above is
        # computed from `clears_threshold` and `grouped_clears` only, so adding this
        # block cannot move it, and that is deliberate: it was written after the
        # pre-registered statistic was seen to fail.
        "cluster_corrected_estimand": cluster_corrected,
        "two_estimands": _TWO_ESTIMANDS,
        # What the mode reader made of each scored image, and how the rate splits by it.
        # 166 of pool B's 303 are UNRESOLVED to that reader, which the pooled rate hides.
        "mode_decomposition": _by_mode_verdict(scored),
        "axis_sign_scope": _axis_sign_scope(args.snapshot, scored),
        "not_testable_note": (
            "A corrected corridor is identically 0 Hz across the pass, so it is a "
            "vertical line with a free horizontal offset and predicts no shape. "
            "Gate 3 can only be asked of uncorrected captures, where an S-curve is "
            "predicted and can be wrong. Excluding these is a limit on the gate's "
            "scope, not a pass."
        ),
        "thresholds": {
            "z_min": DEFAULT_THRESHOLDS.z_min,
            "min_detect_frac": DEFAULT_THRESHOLDS.min_detect_frac,
            "coverage_threshold": DEFAULT_THRESHOLDS.coverage_threshold,
            "offset_ppm_limit": DEFAULT_THRESHOLDS.offset_ppm_limit,
            "filter_width": DEFAULT_THRESHOLDS.filter_width,
            "search_window_factor": DEFAULT_THRESHOLDS.search_window_factor,
            "seed": DEFAULT_THRESHOLDS.seed,
        },
        "threshold_rationale": THRESHOLD_RATIONALE,
        "claim": {
            "established": (
                "After fitting one constant frequency offset bounded at 50 ppm, the "
                "predicted Doppler SHAPE fits the observed trace significantly better "
                "than corridors built by permuting the same Doppler values in time, "
                "and better than the same curve rescaled to 0.25x, 0.5x, 2x or 4x its "
                "predicted swing. The shape and the magnitude of the SGP4 prediction "
                "are both doing work."
            ),
            "not_established": (
                "That the corridor sits where physics places it without a fitted "
                "offset. All three fitted offsets are 40 to 84 percent of their own "
                "predicted swing, so each needed a large slide to fit. This is a "
                "shape test, not an absolute-position test, and the plan's phrase "
                "'corridor intersects a visible trace' is looser than what is "
                "measured here. The per-row position diagnostic (fit.coverage, "
                "fit.corridor_hit) is null on every scored observation because these "
                "traces do not clear the per-row detection floor."
            ),
            "why_the_offset_is_not_a_fudge": (
                "A cubesat oscillator drifts and the SatNOGS transmitter frequency a "
                "station tunes to is community-maintained, so an absolute-position "
                "test would be testing the database rather than the orbital "
                "mechanics. The offset is a real physical quantity and is reported "
                "per observation as fitted_offset_ppm."
            ),
        },
        "method": (
            "Per observation: fit one constant frequency offset bounded at "
            "offset_ppm_limit ppm of the downlink, scoring the predicted curve with "
            "a matched filter and taking the best offset. Then repeat the identical "
            "fit for n_nulls corridors built by permuting the observation's own "
            "Doppler samples in time, which preserves every frequency value and the "
            "whole swing while destroying the monotone shape. The statistic is the "
            "one-sided empirical p-value of the true corridor against that null "
            "distribution. An observation discriminates when p <= p_value_max. The "
            "gate passes when the discriminating rate over scored observations "
            "reaches the threshold. Per-row residuals and coverage are reported as "
            "diagnostics but are not the gate: these traces integrate to "
            "significance along the path while individual rows stay below z_min, so "
            "a per-row instrument reports zero detections on a trace A3 localised "
            "at high sigma."
        ),
        "observations": results,
        "skipped": [p for p in prepared if "zs" not in p],
    }

    args.out.parent.mkdir(parents=True, exist_ok=True)
    # Non-finite floats out, then `allow_nan=False` so a value this missed stops the
    # writer rather than producing a file only Python can read.
    non_finite: list[str] = []
    receipt = _json_safe(receipt, "", non_finite)
    if non_finite:
        logger.warning(
            "%d non-finite value(s) written as null, because JSON has no NaN: %s",
            len(non_finite),
            ", ".join(non_finite[:8]) + (" ..." if len(non_finite) > 8 else ""),
        )
    args.out.write_text(
        json.dumps(receipt, indent=2, allow_nan=False), encoding="utf-8", newline="\n"
    )

    print()
    print("=" * 72)
    print(f"KILL GATE 3: {verdict}")
    print("=" * 72)
    print(f"  decisive observations   {len(decisive)}")
    print(f"  testable (has a shape)  {len(testable)}")
    print(f"  not testable (flat)     {len(not_testable)}")
    print(f"  scored against nulls    {len(scored)}")
    print(f"  stations / sats / days  "
          f"{grouping['distinct_stations']} / {grouping['distinct_satellites']}"
          f" / {grouping['distinct_days']}")
    g_rate = grouping["grouped_discriminating_rate"]
    g_txt = f"{g_rate:.3f}" if g_rate is not None else "n/a"
    print(f"  grouped rate            {g_txt}"
          f"  over {grouping['groups_scored']} {grouping['group_key']} groups")
    print(f"  per-observation rate    "
          f"{f'{hit_rate:.3f}' if hit_rate is not None else 'n/a'}"
          f"  (threshold {args.gate_threshold})")
    print()
    for r in scored:
        c = r["null_calibration"]
        scaled = "  ".join(f"{k}={v:.2f}" for k, v in c["scaled_swing_sigmas"].items())
        print(f"    obs {r['obs_id']}  sigma={c['true_sigma']:.2f}  "
              f"null_med={c['null_median']:.2f}  null_max={c['null_max']:.2f}  "
              f"margin={c['margin_over_best_null']:+.2f}")
        print(f"        {c['n_at_least']} of {c['n_nulls']} nulls reached it, "
              f"p={c['p_value']:.4f}  |  scaled swing: {scaled}  "
              f"beats_scaled={c['beats_scaled_swing']}")
    print()
    print(f"  receipt                 {args.out}")
    print("=" * 72)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
