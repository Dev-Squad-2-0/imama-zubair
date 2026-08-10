"""Task 3: aggregate production performance metrics.
Run Task 1 first so evaluation_results.json exists.
"""
import json, os, re, sqlite3, statistics, sys
from pathlib import Path
HERE=Path(__file__).resolve().parent; ROOT=HERE.parent.parent
sys.path.insert(0,str(ROOT/'src'))

RAG_CASES=[
 ('What documents are needed to buy a property?', ['cnic','nicop']),
 ('Do you offer installment plans?', ['10 percent','payment plans']),
 ('Can overseas Pakistanis buy property remotely?', ['power of attorney','video verification']),
 ('What is the token amount to book a property?', ['5 to 10 percent','token']),
 ('Do you charge any agent commission?', ['1 percent','commission']),
 ('Are these properties verified and legal?', ['noc','clear title']),
 ('Do you offer virtual property tours?', ['video call','walkthrough']),
 ('What is the typical rental deposit amount?', ['one to two months','deposit']),
 ('Are utility bills included in rent?', ['separately','utility']),
 ('Do you provide legal assistance during purchase?', ['panel lawyers','sale agreement']),
]

def pct(values,p):
    if not values:return 0
    xs=sorted(values); k=(len(xs)-1)*p; f=int(k); c=min(f+1,len(xs)-1)
    return xs[f] if f==c else xs[f]+(xs[c]-xs[f])*(k-f)

def memory_benchmark():
    from conversation_memory import ConversationMemory
    cases=[
      ([('Mera naam Ali hai',False),('DHA Phase 6',False),('apartment',False)], {'client_name':'Ali','area':'DHA Phase 6','property_type':'apartment'}),
      ([('Mera budget 3 crore hai',False),('F-10 Islamabad',False),('3 bedroom house',False)], {'budget':30000000,'city':'Islamabad','area':'F-10','bedrooms':3,'property_type':'house'}),
      ([('میرا نام حسن ہے',False),('جوہر ٹاؤن لاہور',False),('اپارٹمنٹ',False)], {'client_name':'حسن','city':'Lahore','area':'Johar Town','property_type':'apartment'}),
      ([('Rent nahi, buy karna hai',False),('DHA Phase 6',False)], {'purpose':'buy','area':'DHA Phase 6'}),
      ([('Ali',True),('Bahria Town Islamabad',False)], {'client_name':'Ali','city':'Islamabad','area':'Bahria Town'}),
    ]
    passed=0; details=[]
    for turns,expected in cases:
        m=ConversationMemory()
        for text,expect_name in turns:m.update_from_customer_text(text,expect_name=expect_name)
        actual={k:getattr(m.slots,k) for k in expected}
        ok=all(actual[k]==v for k,v in expected.items()); passed+=ok
        details.append({'turns':[x[0] for x in turns],'expected':expected,'actual':actual,'passed':ok})
    return {'accuracy_percent':round(100*passed/len(cases),2),'passed':passed,'total':len(cases),'details':details}

def rag_benchmark():
    try:
        import rag_pipeline
        col=rag_pipeline.get_collection()
    except Exception as exc:
        return {'available':False,'error':str(exc),'accuracy_percent':None,'hallucination_proxy_percent':None,'details':[]}
    good=0; halluc=0; details=[]
    for q,terms in RAG_CASES:
        try:
            hits=rag_pipeline.retrieve(col,q,top_k=3); context='\n'.join(h['text'] for h in hits).lower()
            retrieval_ok=any(t in context for t in terms); good+=retrieval_ok
            answer,mode=rag_pipeline.generate_answer(q,hits); low=(answer or '').lower()
            answer_ok=any(t in low for t in terms)
            nums=set(re.findall(r'\b\d+(?:\.\d+)?\b',low)); context_nums=set(re.findall(r'\b\d+(?:\.\d+)?\b',context))
            unsupported_numbers=sorted(nums-context_nums)
            case_halluc=bool(unsupported_numbers) or (not answer_ok and mode=='llm_generated')
            halluc+=case_halluc
            details.append({'query':q,'expected_terms':terms,'retrieval_ok':retrieval_ok,'answer_ok':answer_ok,'mode':mode,'unsupported_numbers':unsupported_numbers,'hallucination_proxy':case_halluc})
        except Exception as exc:
            details.append({'query':q,'error':str(exc),'retrieval_ok':False,'hallucination_proxy':True}); halluc+=1
    return {'available':True,'accuracy_percent':round(100*good/len(RAG_CASES),2),'hallucination_proxy_percent':round(100*halluc/len(RAG_CASES),2),'details':details}

def main():
    eval_path=HERE/'output'/'evaluation_results.json'
    if not eval_path.exists():
        print('Run: python tests/production_eval/run_evaluation_suite.py first'); return 2
    ev=json.loads(eval_path.read_text(encoding='utf-8')); results=ev['results']; summary=ev['summary']
    scenario_ok=[not r.get('error') and all(c['status']=='PASS' for c in r['checks']) for r in results]
    lat=[t['latency_ms'] for r in results for t in r['turns']]
    booking_attempts=[r for r in results if r['category']=='appointment' and any('booking' in t['trace'] for t in r['turns'])]
    booking_success=[r for r in booking_attempts if (r.get('final_state',{}).get('appointment_status') or {}).get('status')=='booked']
    tool_failures={}
    db=summary.get('eval_db')
    if db and Path(db).exists():
        c=sqlite3.connect(db)
        try:
            for typ,n in c.execute("SELECT event_type,COUNT(*) FROM crm_events WHERE status='failed' GROUP BY event_type"): tool_failures[typ]=n
        finally:c.close()
    metrics={
      'conversation_success_rate_percent':round(100*sum(scenario_ok)/len(scenario_ok),2),
      'latency_ms':{'mean':round(statistics.mean(lat),2) if lat else 0,'p50':round(pct(lat,.5),2),'p95':round(pct(lat,.95),2),'max':round(max(lat),2) if lat else 0},
      'booking_success':{'successful':len(booking_success),'attempts':len(booking_attempts),'rate_percent':round(100*len(booking_success)/len(booking_attempts),2) if booking_attempts else None},
      'tool_failures':tool_failures,
      'rag':rag_benchmark(),
      'memory':memory_benchmark(),
    }
    metrics['hallucination_rate_percent']=metrics['rag'].get('hallucination_proxy_percent')
    out=HERE/'output'/'performance_results.json'; out.write_text(json.dumps(metrics,ensure_ascii=False,indent=2),encoding='utf-8')
    lines=['# Performance Evaluation','',f"- Conversation success: **{metrics['conversation_success_rate_percent']}%**",f"- Mean latency: **{metrics['latency_ms']['mean']} ms**",f"- P95 latency: **{metrics['latency_ms']['p95']} ms**",f"- Booking success: **{metrics['booking_success']['rate_percent']}%** ({metrics['booking_success']['successful']}/{metrics['booking_success']['attempts']})",f"- Memory accuracy: **{metrics['memory']['accuracy_percent']}%**",f"- RAG retrieval accuracy: **{metrics['rag'].get('accuracy_percent')}%**",f"- Hallucination/grounding proxy: **{metrics['hallucination_rate_percent']}%**",'', '> Hallucination is a benchmark proxy: unsupported numeric claims or a generated answer missing the expected grounded fact. It is not a perfect semantic hallucination detector.','', '## Tool failures','']
    lines += [f'- {k}: {v}' for k,v in tool_failures.items()] or ['- None recorded in the isolated evaluation DB.']
    (HERE/'output'/'performance_results.md').write_text('\n'.join(lines),encoding='utf-8')
    print(json.dumps(metrics,ensure_ascii=False,indent=2)); return 0
if __name__=='__main__': raise SystemExit(main())
