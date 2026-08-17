# C2 pre-registration

Written and committed before the numbers below were measured, so that no
threshold in this unit can be chosen after seeing what it produces. The C1 prompt's
rule, applied to C2: fix the definition, then measure.

Committed: 2026-08-18, before `run_queue.py` was run with any cap in place.

## 1. Episode key

The queue and the fusion pipeline group by `(ground_station, norad_cat_id,
start[:13])`, an hour bucket. `splits.py` groups by `(ground_station,
norad_cat_id, orbital_revolution)`, computed from TLE mean motion. Both are called
"pass episode" in the receipts.

**Decision:** the canonical key is the `splits.py` one, and the queue and fusion
adopt it. An hour bucket splits any pass crossing an hour boundary into two
groups, which is pseudoreplication in the resampling unit, and it is the same
class of error as reading three measurements that shared two ground stations as
three independent confirmations.

**Measured effect before the change,** so the size of the correction is on record
rather than asserted: 2716 revolution episodes against 2722 hour buckets over
2727 observations. 7 revolution episodes, holding 17 observations, are split
across more than one hour bucket. 1 hour bucket merges 2 revolutions, holding 4
observations. The numerical effect on this single-evening corpus is therefore
small. On a multi-day snapshot it would not be, because the hour bucket has no
orbital meaning.

## 2. The grouping the interval should use

**Measured, and it is the reason this unit changed shape.** Mean observations per
revolution episode is 1.004, and only 8 of 2716 episodes hold more than one
observation. An episode-grouped bootstrap on this corpus is therefore almost
exactly an ordinary bootstrap: there is no within-episode correlation for it to
absorb, because episodes are nearly singletons.

The correlation is at the station. On the chronological test partition, 143
stations hold 409 observations, mean cluster 2.86, largest 16. The one-way
intra-class correlation of the actionable-conflict indicator across stations is
0.1409, giving a design effect of 1.262. Station 5078 carries conflicts on 4 of 7
captures and 5068 and 5024 on half of theirs, while 45 of the 53 stations with at
least 3 observations carry none. The overall conflict rate is 0.0538.

A receiver and its local-oscillator error are properties of a station and persist
across passes, which is the justification the grouped interval was given in the
first place.

**Decision:** report both intervals, always. The episode-grouped interval stays,
because it is what Waves B and C have published and it is the finer grouping. A
station-clustered interval is added, and because every episode lies within exactly
one station, station clustering subsumes episode clustering and is the
conservative one. **The gate 6 verdict is decided by the wider of the two, named
explicitly in the receipt.** Choosing the narrower interval after seeing which one
clears the threshold is the failure this rule exists to prevent, so the rule is
fixed here, before either was computed on the shipped queue.

The ICC and the design effect are reported in the receipt beside the intervals, so
a reader can see why two intervals exist.

## 3. Entity-concentration caps

Fixed now, before measuring their effect on lift.

| Entity | Cap within the review budget | Value at budget 50 |
|---|---|---|
| Ground station | 10% of the budget | 5 entries |
| Transmitter | 20% of the budget | 10 entries |

Rationale, stated before the measurement. The corpus holds 271 stations and 613
transmitters over 2727 observations. Five entries is enough for a reviewer to
recognise a systematic fault at one site, and 10% leaves 45 slots for the rest of
the network. The transmitter cap is looser at 20% because one transmitter already
holds 312 observations, 11.4% of the corpus, so a cap at its corpus share would
bind on ordinary data rather than on flooding.

Enforcement is a single greedy pass down the ranking: an entry whose station or
transmitter quota is exhausted is displaced below the budget line, keeps its place
in the full queue, and carries a queue reason recording why it was displaced. It
is not deleted, because a displaced observation is still a real candidate and a
silently dropped row is a suppressed finding.

## 4. Which queue the gate is measured on

**The shipped queue is the capped queue,** because duplicate-safe diversity is a
product requirement and not an optimisation. Gate 6 is measured on it.

The uncapped lift is also computed and reported, as a reference point for the cost
of diversity. It is not eligible to be the verdict. If capping lowers lift, that
is the measured price of not spending a reviewer's budget on one station, and it
is reported as such rather than resolved by picking whichever queue scores better.

## 4a. Addendum, added after measuring: which population the ICC is computed on

The 0.1409 quoted in section 2 was measured over all 409 ranked observations of
the chronological test partition, which is what motivated adopting the station
grouping. The receipt reports the ICC over the 88 decisively-labelled observations
instead, because those are the rows the conflict indicator exists for and the
population the interval is drawn from. On that subset it is 0.0887 with a design
effect of 1.132. Both are real; they are different populations, and the receipt's
is the one the verdict depends on. Recorded here so the two numbers are not read
as a discrepancy.

Measured on the decisive subsets, station clustering is present on every split:
chronological 0.0887, cold_station 0.0784, cold_transmitter 0.1347, cold_combined
0.0909, with design effects from 1.132 to 1.552.

The episode ICC on the same subsets is not measurable at all, and that is the
finding that reshaped this unit: the 88 decisive observations of the chronological
test partition fall into 87 pass episodes, mean size 1.000. There is no
within-episode variance to partition, so the episode-grouped bootstrap published
throughout Waves B and C was resampling singleton groups.

## 5. What would falsify the caps

If the caps displace so few entries that they never bind, they are decoration and
the receipt must say so with the count, in the same way the SHA-256 duplicate rule
reports zero duplicates in the corpus rather than implying it was exercised.
