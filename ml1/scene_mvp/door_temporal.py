"""Causal experimental door-state confirmation; no labels used by the filter."""
import math

SPEC = {'version': 1, 'min_observations': 2, 'min_span_sec': .5,
        'max_gap_sec': .75, 'unknown_policy': 'reset_no_imputation',
        'transition_policy': 'unknown_until_confirmed'}


def confirm(rows):
    """Consume only timestamps and raw predictions. Never backdate state output."""
    result = []
    stable = candidate = None
    count = 0
    start = previous = None
    for row in rows:
        t, raw = float(row['timestamp_sec']), row['predicted']
        if not math.isfinite(t) or t < 0 or (previous is not None and t <= previous):
            raise ValueError('Strictly increasing finite timestamps required')
        if raw not in ('open', 'closed', 'unknown'):
            raise ValueError('Invalid door state')
        gap = previous is not None and t - previous > SPEC['max_gap_sec']
        previous = t
        if gap or raw == 'unknown':
            stable = candidate = None
            start = None
            count = 0
        if raw == 'unknown':
            state, reason = 'unknown', 'raw_unknown'
        elif raw == stable:
            state, reason = stable, 'confirmed_continuation'
        else:
            stable = None
            if raw != candidate:
                candidate, count, start = raw, 1, t
            else:
                count += 1
            if count >= SPEC['min_observations'] and t-start >= SPEC['min_span_sec']-1e-3:
                stable = raw
                state, reason = raw, 'confirmed_now'
            else:
                state, reason = 'unknown', 'awaiting_confirmation'
        result.append({'timestamp_sec': t, 'predicted': state,
                       'raw_predicted': raw, 'reason': reason,
                       'evidence_start_sec': start if state != 'unknown' else None})
    return result


def episodes(rows, key, state='open', max_gap_sec=.75):
    """Contiguous sampled runs only; unknown gaps are never filled."""
    result = []
    active = None
    for row in rows:
        t = row['timestamp_sec']
        if row[key] != state:
            active = None
            continue
        if active is None or t-active['last_observed_sec'] > max_gap_sec:
            active = {'first_observed_sec': t, 'last_observed_sec': t, 'frames': 0}
            result.append(active)
        active['last_observed_sec'] = t
        active['frames'] += 1
    return result


def episode_metrics(truth_rows, filtered):
    truth = episodes(truth_rows, 'expected')
    predicted = episodes(filtered, 'predicted')
    def overlap(a, b):
        return max(a['first_observed_sec'], b['first_observed_sec']) <= min(a['last_observed_sec'], b['last_observed_sec'])
    matched = []
    for actual in truth:
        hits = [p for p in predicted if overlap(actual, p)]
        matched.append(dict(actual, overlapping_prediction_runs=len(hits),
                            first_confirmation_delay_sec=(min(p['first_observed_sec'] for p in hits)-actual['first_observed_sec']) if hits else None))
    return {'human_open_runs': len(truth), 'predicted_open_runs': len(predicted),
            'human_runs_with_any_overlap': sum(r['overlapping_prediction_runs'] > 0 for r in matched),
            'predicted_runs_without_overlap': sum(not any(overlap(p, a) for a in truth) for p in predicted),
            'human_runs': matched, 'predicted_runs': predicted,
            'limitation': 'Sampled overlap only; fragmented detections are counted separately. Not precise physical transition times.'}
