"""Conservative promotion criterion, using the same cases for both methods."""
from statistics import mean


def promotion_gate(baseline: list[dict], candidate: list[dict], *, max_extra_sec: float = 5) -> dict:
    def valid(rows):
        return {(r['video'],r['variant']):r for r in rows
                if 'stability' in r and r.get('status','ok')=='ok'}
    reference,current=valid(baseline),valid(candidate)
    reasons=[]
    if not reference or set(reference)!=set(current):
        reasons.append('coverage_or_availability_changed')
    keys=set(reference)&set(current)
    improved=False
    for name in ('role','near_table','near_machine'):
        if not keys:continue
        before=mean(reference[k]['stability'][name] for k in keys)
        after=mean(current[k]['stability'][name] for k in keys)
        if after < before-1e-9:reasons.append(name+'_less_stable')
        if name!='role' and after>before+1e-9:improved=True
    if not improved:reasons.append('no_presence_stability_improvement')
    times=[r['extra_sec'] for r in candidate if 'extra_sec'in r and r.get('status','ok')=='ok']
    if not times or max(times)>max_extra_sec:reasons.append('time_budget_exceeded')
    return dict(passed=not reasons,reasons=reasons)
