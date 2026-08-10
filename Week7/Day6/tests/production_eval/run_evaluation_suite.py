"""Task 1: run all 40+ production conversation scenarios safely."""
import json, os, sys, time, statistics
from collections import Counter, defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
sys.path.insert(0, str(ROOT/'src'))
sys.path.insert(0, str(HERE))
from runtime import prepare_isolated_runtime
from evaluation_suite import ALL_SCENARIOS

RUN_ID = time.strftime('%Y%m%d%H%M%S')
EVAL_DB = prepare_isolated_runtime(RUN_ID, mock_writes=os.getenv('EVAL_REAL_WRITES','0') != '1')
import graph


def percentile(values, p):
    if not values: return 0.0
    xs=sorted(values); k=(len(xs)-1)*p; f=int(k); c=min(f+1,len(xs)-1)
    return xs[f] if f==c else xs[f]+(xs[c]-xs[f])*(k-f)


def run_scenario(sc, index):
    sid=f'prod-eval-{sc["id"]}-{RUN_ID}'
    phone=f'0300{index:07d}'[-11:]
    turns=[]; traces=[]; replies=[]; latencies=[]
    error=None
    try:
        for text in sc['turns']:
            t0=time.perf_counter(); reply, trace=graph.run_turn(sid,text,caller_id=phone); ms=(time.perf_counter()-t0)*1000
            names=[x['node_name'] for x in trace]
            turns.append({'customer_text':text,'agent_reply':reply,'trace':names,'latency_ms':round(ms,2)})
            traces.append(names); replies.append(reply); latencies.append(ms)
    except Exception as exc:
        error=f'{type(exc).__name__}: {exc}'
    state=graph.get_session_state(sid) or {}
    checks=[]
    if error:
        checks=[{'label':'scenario completed without unhandled exception','status':'FAIL'}]
    else:
        for label, fn in sc.get('checks',[]):
            try: ok=bool(fn(state,traces,replies))
            except Exception as exc: ok=False; label=f'{label} (check raised {type(exc).__name__}: {exc})'
            checks.append({'label':label,'status':'PASS' if ok else 'FAIL'})
        if not checks: checks=[{'label':'scenario ran to completion','status':'PASS'}]
    return {'id':sc['id'],'category':sc['category'],'description':sc['description'],'turns':turns,'checks':checks,'error':error,
            'latency_ms':{'mean':round(statistics.mean(latencies),2) if latencies else 0,'p95':round(percentile(latencies,.95),2),'max':round(max(latencies),2) if latencies else 0},
            'final_state':{'intent':state.get('intent'),'appointment_status':state.get('appointment_status'),'missing_fields':state.get('missing_fields'),'clarification_needed':state.get('clarification_needed')}}


def main():
    print(f'Running {len(ALL_SCENARIOS)} production scenarios across {len(set(x["category"] for x in ALL_SCENARIOS))} categories')
    results=[]
    for i,sc in enumerate(ALL_SCENARIOS,1):
        print(f'[{i:02d}/{len(ALL_SCENARIOS)}] {sc["id"]}: {sc["description"]}')
        r=run_scenario(sc,i); results.append(r)
        for c in r['checks']: print(f'  [{c["status"]}] {c["label"]}')
        if r['error']: print('  ERROR:',r['error'])
    scenario_pass=[not r['error'] and all(c['status']=='PASS' for c in r['checks']) for r in results]
    cats=Counter(r['category'] for r in results)
    by_cat=defaultdict(lambda:{'passed':0,'total':0})
    all_turn_lat=[]
    for r,ok in zip(results,scenario_pass):
        by_cat[r['category']]['total']+=1; by_cat[r['category']]['passed']+=int(ok)
        all_turn_lat += [t['latency_ms'] for t in r['turns']]
    summary={'run_id':RUN_ID,'scenario_count':len(results),'category_count':len(cats),'scenario_success_rate':round(100*sum(scenario_pass)/len(results),2),
             'turn_latency_ms':{'mean':round(statistics.mean(all_turn_lat),2) if all_turn_lat else 0,'p50':round(percentile(all_turn_lat,.5),2),'p95':round(percentile(all_turn_lat,.95),2),'max':round(max(all_turn_lat),2) if all_turn_lat else 0},
             'by_category':dict(by_cat),'eval_db':str(EVAL_DB)}
    payload={'summary':summary,'results':results}
    out=HERE/'output'; out.mkdir(exist_ok=True)
    (out/'evaluation_results.json').write_text(json.dumps(payload,ensure_ascii=False,indent=2),encoding='utf-8')
    lines=['# Production Evaluation Suite','',f"**Scenarios:** {len(results)}",f"**Success rate:** {summary['scenario_success_rate']}%",f"**Mean turn latency:** {summary['turn_latency_ms']['mean']} ms",f"**P95 turn latency:** {summary['turn_latency_ms']['p95']} ms",'', '## Categories','', '| Category | Passed | Total |','|---|---:|---:|']
    for cat,v in sorted(by_cat.items()): lines.append(f"| {cat} | {v['passed']} | {v['total']} |")
    lines += ['','## Scenario results','']
    for r,ok in zip(results,scenario_pass): lines.append(f"- {'PASS' if ok else 'FAIL'} `{r['id']}` — {r['description']}")
    (out/'evaluation_results.md').write_text('\n'.join(lines),encoding='utf-8')
    print('\nSummary:',json.dumps(summary,indent=2))
    return 0 if all(scenario_pass) else 1
if __name__=='__main__': raise SystemExit(main())
