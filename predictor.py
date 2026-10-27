"""Football research prototype; no trained model or claimed predictive advantage.
Input: normalized JSONL. Output: text plus optional internal JSON audit report.
"""
import argparse
import hashlib
import json
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import sklearn
from scipy.optimize import least_squares
from scipy.stats import poisson
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.linear_model import PoissonRegressor
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

VERSION = "0.1.0-research"


def ts(value):
    result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if result.tzinfo is None:
        raise ValueError("Timezone required")
    return result.astimezone(timezone.utc)


def validate(row):
    for key in ["match_id", "competition_id", "season", "segment", "home_team_id",
                "away_team_id", "kickoff_utc", "source"]:
        if not isinstance(row.get(key), str) or not row[key]:
            raise ValueError(f"Missing string field: {key}")
    if type(row.get("neutral_venue")) is not bool:
        raise ValueError("neutral_venue must be boolean")
    if row["home_team_id"] == row["away_team_id"]:
        raise ValueError("Teams must differ")
    kickoff = ts(row["kickoff_utc"])
    scores = [row.get(k) for k in ["home_goals_90", "away_goals_90"]]
    if any(x is not None for x in scores):
        if any(type(x) is not int or not 0 <= x <= 100 for x in scores):
            raise ValueError("Both scores must be nonnegative integers <=100")
        if row.get("status") != "FINISHED" or row.get("score_scope") != "REGULATION":
            raise ValueError("Only FINISHED REGULATION labels supported")
        if ts(row["result_available_at_utc"]) <= kickoff:
            raise ValueError("Result cannot be available before or at kickoff")
        if row.get("availability_basis") not in {"archived", "reconstructed"}:
            raise ValueError("Specify archived or reconstructed result availability")
    for snap in row.get("odds_snapshots", []):
        if not snap.get("bookmaker"):
            raise ValueError("Odds bookmaker required")
        if ts(snap["available_at_utc"]) < ts(snap["quoted_at_utc"]):
            raise ValueError("Odds availability precedes quote")
        for key in ["home", "draw", "away", "over25", "under25"]:
            val = snap.get(key)
            if type(val) not in (int, float) or not np.isfinite(val) or val <= 1:
                raise ValueError(f"Complete decimal odds row required: {key}")
    return row


def load(path):
    rows, seen = [], set()
    for i, line in enumerate(Path(path).read_text(encoding="utf-8-sig").splitlines(), 1):
        if not line.strip():
            continue
        try:
            row = validate(json.loads(line))
            if row["match_id"] in seen:
                raise ValueError("Duplicate match ID")
            seen.add(row["match_id"])
            rows.append(row)
        except (ValueError, KeyError, TypeError) as exc:
            raise ValueError(f"Line {i}: {exc}") from exc
    return rows


def points(pred, actual):
    if tuple(pred) == tuple(actual):
        return 10000
    return 4000 if np.sign(pred[0]-pred[1]) == np.sign(actual[0]-actual[1]) else 0


def grid(h, a):
    if not all(np.isfinite(x) and 0 < x <= 20 for x in [h, a]):
        raise ValueError("Rates must be in (0,20]")
    n = max(10, int(poisson.ppf(1-1e-12, max(h, a)))+1)
    p = np.outer(poisson.pmf(np.arange(n), h), poisson.pmf(np.arange(n), a))
    tail = max(0., 1-float(p.sum()))
    p /= p.sum()
    outcome = np.array([np.tril(p, -1).sum(), np.trace(p), np.triu(p, 1).sum()])
    return p, outcome, tail


def select(h, a):
    p, outcome, tail = grid(h, a)
    hi, ai = np.indices(p.shape)
    oi = np.where(hi > ai, 0, np.where(hi == ai, 1, 2))
    utility = 4000*outcome[oi] + 6000*p
    best = tuple(int(v) for v in np.unravel_index(np.argmax(utility), p.shape))
    return dict(score=list(best), expected_points=float(utility[best]),
                outcome_probabilities=outcome.tolist(), exact_probability=float(p[best]),
                rates=[float(h), float(a)], omitted_tail=tail)


class Stat:
    def __init__(self):
        self.w = self.first = self.second = 0.
        self.at = self.last_kickoff = None

    def decay(self, at):
        if self.at is not None:
            factor = 2**(-(at-self.at).total_seconds()/(180*86400))
            self.w *= factor
            self.first *= factor
            self.second *= factor
        self.at = at

    def add(self, first, second, at, kickoff):
        self.decay(at)
        self.w += 1
        self.first += first
        self.second += second
        self.last_kickoff = max(kickoff, self.last_kickoff or kickoff)


def features(fixtures, history, cutoffs):
    """Sorted availability sweep: no result at or after cutoff enters a feature."""
    events = sorted([r for r in history if r.get("home_goals_90") is not None],
                    key=lambda r: ts(r["result_available_at_utc"]))
    teams, leagues, segments = defaultdict(Stat), defaultdict(Stat), defaultdict(Stat)
    output, pointer = [None]*len(fixtures), 0
    for i in sorted(range(len(fixtures)), key=lambda x: cutoffs[x]):
        r, at = fixtures[i], cutoffs[i]
        while pointer < len(events) and ts(events[pointer]["result_available_at_utc"]) < at:
            e = events[pointer]
            when, kick = ts(e["result_available_at_utc"]), ts(e["kickoff_utc"])
            seg, comp, hg, ag = e["segment"], e["competition_id"], e["home_goals_90"], e["away_goals_90"]
            teams[(seg, e["home_team_id"])].add(hg, ag, when, kick)
            teams[(seg, e["away_team_id"])].add(ag, hg, when, kick)
            leagues[(seg, comp)].add(hg, ag, when, kick)
            segments[seg].add(hg, ag, when, kick)
            pointer += 1
        seg = r["segment"]
        league, pooled = leagues[(seg, r["competition_id"])], segments[seg]
        league.decay(at)
        pooled.decay(at)
        if pooled.w == 0:
            continue
        # Initial shrinkage settings; not tuned or shown to be optimal.
        bh = (league.first + 10*pooled.first/pooled.w)/(league.w+10)
        ba = (league.second + 10*pooled.second/pooled.w)/(league.w+10)
        prior = (bh+ba)/2
        states = []
        for key in ["home_team_id", "away_team_id"]:
            s = teams[(seg, r[key])]
            s.decay(at)
            states.append([(s.first+5*prior)/(s.w+5), (s.second+5*prior)/(s.w+5),
                           np.log1p(s.w), min(60., (at-s.last_kickoff).total_seconds()/86400)
                           if s.last_kickoff else 60.])
        output[i] = np.array([
            [0 if r["neutral_venue"] else (1 if side == 0 else -1), bh, ba,
             *states[side][:2], *states[1-side][:2],
             states[side][2], states[1-side][2], states[side][3], states[1-side][3]]
            for side in [0, 1]])
    return output


def fit(history, asof, hours_before, kind, minimum=100):
    train = [r for r in history if r.get("home_goals_90") is not None and
             ts(r["result_available_at_utc"]) < asof]
    cuts = [ts(r["kickoff_utc"])-timedelta(hours=hours_before) for r in train]
    xs, models = features(train, train, cuts), {}
    for seg in {r["segment"] for r in train}:
        ix = [i for i, r in enumerate(train) if r["segment"] == seg and xs[i] is not None]
        if len(ix) < minimum:
            continue
        x = np.concatenate([xs[i] for i in ix])
        y = np.array([train[i][k] for i in ix for k in ["home_goals_90", "away_goals_90"]])
        if y.sum() == 0:
            continue
        weights = np.array([2**(-(asof-ts(train[i]["kickoff_utc"])).days/365)
                            for i in ix for _ in range(2)])
        if kind == "poisson":
            model = make_pipeline(StandardScaler(), PoissonRegressor(alpha=.1, max_iter=500))
            model.fit(x, y, poissonregressor__sample_weight=weights)
        elif kind == "boosted":
            model = HistGradientBoostingRegressor(loss="poisson", max_iter=100,
                max_leaf_nodes=15, min_samples_leaf=30, l2_regularization=5,
                early_stopping=False, random_state=17)
            model.fit(x, y, sample_weight=weights)
        else:
            raise ValueError("Unknown model")
        models[seg] = model
    return models


def market(row, at):
    latest = {}
    for s in row.get("odds_snapshots", []):
        quoted = ts(s["quoted_at_utc"])
        if quoted <= at and ts(s["available_at_utc"]) <= at and at-quoted <= timedelta(hours=24):
            previous = latest.get(s["bookmaker"])
            if previous is None or quoted > ts(previous["quoted_at_utc"]):
                latest[s["bookmaker"]] = s
    if not latest:
        return None
    targets = []
    for s in latest.values():
        p = 1/np.array([s[k] for k in ["home", "draw", "away"]])
        p /= p.sum()
        g = 1/np.array([s["over25"], s["under25"]])
        g /= g.sum()
        targets.append([*p, g[0]])
    target = np.mean(targets, axis=0)

    def residual(log_rates):
        rates = np.exp(log_rates)
        _, outcome, _ = grid(*rates)
        return np.r_[outcome, poisson.sf(2, rates.sum())]-target

    result = least_squares(residual, np.log([1.5, 1.2]),
                           bounds=(np.log([.03, .03]), np.log([10., 10.])))
    if not result.success:
        return None
    pred = select(*np.exp(result.x))
    pred.update(market_max_probability_error=float(np.max(np.abs(result.fun))),
                bookmakers=sorted(latest))
    return pred


def predict(fixtures, history, cutoffs, models, kind):
    xs = features(fixtures, history, cutoffs) if kind != "market" else [None]*len(fixtures)
    results = []
    for r, at, x in zip(fixtures, cutoffs, xs):
        if at >= ts(r["kickoff_utc"]):
            raise ValueError("Prediction must precede kickoff")
        item = dict(match_id=r["match_id"], competition_id=r["competition_id"],
                    segment=r["segment"], model=kind, asof_utc=at.isoformat())
        if kind == "market":
            pred = market(r, at)
        elif x is not None and r["segment"] in models:
            rates = models[r["segment"]].predict(x)
            pred = select(*rates) if np.all((rates > 0) & (rates <= 20)) else None
        else:
            pred = None
        if pred is None:
            item.update(status="unavailable", reason="Insufficient supported history/model or odds")
        else:
            item.update(pred, status="predicted")
            if r.get("home_goals_90") is not None:
                actual = [r["home_goals_90"], r["away_goals_90"]]
                label = 0 if actual[0] > actual[1] else 1 if actual[0] == actual[1] else 2
                p = np.asarray(pred["outcome_probabilities"])
                item.update(actual=actual, points=points(pred["score"], actual),
                    outcome_log_loss=float(-np.log(max(1e-15, p[label]))),
                    outcome_brier=float(np.sum((p-np.eye(3)[label])**2)),
                    exact_log_loss=float(-sum(poisson.logpmf(v, mu) for v, mu in zip(actual, pred["rates"]))))
        results.append(item)
    return results


def walk_forward(rows, start, end, hours_before=24):
    if start >= end or hours_before <= 0:
        raise ValueError("Invalid dates or forecast horizon")
    results, fold = [], start
    while fold < end:
        boundary = (fold.replace(day=1)+timedelta(days=32)).replace(day=1)
        stop = min(boundary, end)
        fixtures = [r for r in rows if r.get("home_goals_90") is not None and
                    fold <= ts(r["kickoff_utc"])-timedelta(hours=hours_before) < stop]
        cuts = [ts(r["kickoff_utc"])-timedelta(hours=hours_before) for r in fixtures]
        if fixtures:
            for kind in ["poisson", "boosted", "market"]:
                models = {} if kind == "market" else fit(rows, fold, hours_before, kind)
                results.extend(predict(fixtures, rows, cuts, models, kind))
        fold = stop
    return results


def summary(results):
    groups = defaultdict(list)
    for r in results:
        groups[(r["model"], "ALL")].append(r)
        groups[(r["model"], r["competition_id"])].append(r)
    reports = []
    for (model, comp), rows in sorted(groups.items()):
        scored = [r for r in rows if "points" in r]
        reports.append(dict(model=model, competition=comp, eligible=len(rows),
            scored=len(scored), unavailable=len(rows)-len(scored),
            points=sum(r["points"] for r in scored),
            points_per_scored_match=float(np.mean([r["points"] for r in scored])) if scored else None,
            exact_hits=sum(r["points"] == 10000 for r in scored),
            correct_outcomes=sum(r["points"] > 0 for r in scored),
            **{k: float(np.mean([r[k] for r in scored])) if scored else None
               for k in ["outcome_log_loss", "outcome_brier", "exact_log_loss"]}))
    names = sorted({r["model"] for r in results})
    indexed = {m: {r["match_id"]: r for r in results if r["model"] == m and "points" in r} for m in names}
    paired = []
    for i, left in enumerate(names):
        for right in names[i+1:]:
            common = sorted(set(indexed[left]) & set(indexed[right]))
            differences = [indexed[left][k]["points"]-indexed[right][k]["points"] for k in common]
            paired.append(dict(left=left, right=right, common_matches=len(common),
                mean_points_difference=float(np.mean(differences)) if differences else None))
    return dict(by_model_and_competition=reports, paired_comparisons=paired)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("matches", type=Path)
    parser.add_argument("--start", required=True, help="First prediction timestamp, timezone required")
    parser.add_argument("--end", required=True, help="Exclusive last prediction timestamp")
    parser.add_argument("--hours-before", type=float, default=24)
    parser.add_argument("--output", type=Path, help="Optional internal JSON audit report")
    args = parser.parse_args()
    rows = load(args.matches)
    results = walk_forward(rows, ts(args.start), ts(args.end), args.hours_before)
    report = dict(version=VERSION, sklearn_version=sklearn.__version__,
        input_sha256=hashlib.sha256(args.matches.read_bytes()).hexdigest(),
        settings=dict(start=args.start, end=args.end, hours_before=args.hours_before,
                      feature_half_life_days=180, training_half_life_days=365,
                      hyperparameters="fixed defaults, not tuned"),
        evaluation=summary(results), predictions=results)
    if args.output:
        args.output.write_text(json.dumps(report, indent=2, allow_nan=False), encoding="utf-8")
    for r in report["evaluation"]["by_model_and_competition"]:
        avg = r["points_per_scored_match"]
        print(f"{r['model']} | {r['competition']} | {r['scored']}/{r['eligible']} scored | "
              f"{r['points']} points | average {avg:.1f}" if avg is not None else
              f"{r['model']} | {r['competition']} | no supported predictions")
    for r in report["evaluation"]["paired_comparisons"]:
        print("Paired comparison:", json.dumps(r))


if __name__ == "__main__":
    main()

