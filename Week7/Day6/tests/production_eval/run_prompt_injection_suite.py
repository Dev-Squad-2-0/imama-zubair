"""Task 2: dedicated prompt-injection/guardrail evaluation."""
import json, os, sys, time
from pathlib import Path
HERE=Path(__file__).resolve().parent; ROOT=HERE.parent.parent
sys.path.insert(0,str(ROOT/'src')); sys.path.insert(0,str(HERE))
from runtime import prepare_isolated_runtime
from prompt_injection_suite import ALL_INJECTION_SCENARIOS
RUN_ID=time.strftime('%Y%m%d%H%M%S'); prepare_isolated_runtime('inject-'+RUN_ID, mock_writes=True)
import graph

def main():
    results=[]
    for i,sc in enumerate(ALL_INJECTION_SCENARIOS,1):
        sid=f'inject-{sc["id"]}-{RUN_ID}'; replies=[]; traces=[]; err=None
        try:
            for text in sc['turns']:
                reply,trace=graph.run_turn(sid,text,caller_id=f'0310{i:07d}'[-11:]); replies.append(reply); traces.append([x['node_name'] for x in trace])
        except Exception as exc: err=f'{type(exc).__name__}: {exc}'
        state=graph.get_session_state(sid) or {}; checks=[]
        if err: checks=[{'label':'completed without exception','status':'FAIL'}]
        else:
            for label,fn in sc['checks']:
                try: ok=bool(fn(state,traces,replies))
                except Exception: ok=False
                checks.append({'label':label,'status':'PASS' if ok else 'FAIL'})
        held=not err and all(x['status']=='PASS' for x in checks)
        results.append({'id':sc['id'],'category':sc['category'],'variant':sc['variant'],'guardrail_held':held,'checks':checks,'replies':replies,'error':err})
        print(f"[{'PASS' if held else 'FAIL'}] {sc['id']} — {sc['variant']}")
    rate=100*sum(r['guardrail_held'] for r in results)/len(results)
    payload={'run_id':RUN_ID,'scenario_count':len(results),'guardrail_hold_rate':round(rate,2),'results':results}
    out=HERE/'output'; out.mkdir(exist_ok=True); (out/'prompt_injection_results.json').write_text(json.dumps(payload,ensure_ascii=False,indent=2),encoding='utf-8')
    (out/'prompt_injection_results.md').write_text('# Prompt Injection Results\n\n'+f"Guardrail hold rate: **{rate:.2f}%**\n\n"+'\n'.join(f"- {'PASS' if r['guardrail_held'] else 'FAIL'} `{r['id']}` — {r['variant']}" for r in results),encoding='utf-8')
    return 0 if rate==100 else 1
if __name__=='__main__': raise SystemExit(main())
