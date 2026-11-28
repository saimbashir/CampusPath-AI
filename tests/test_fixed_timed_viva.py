"""Fixed approved question set, server-authoritative timeouts and teacher-only scoring."""
from datetime import datetime,timedelta
from sqlalchemy import select
from app.api import formal_viva as formal
from app.ai import grounded
from app.db import SessionLocal
from app.models import Course,OralSession,OralResponse,now
from tests.test_universal_viva import course_flow,MATERIALS,structured_fake
from tests.test_workflows import good


def make_five(clients):
    t,s,cid,rid,_=course_flow(clients,*MATERIALS[2])
    ex=good(t.post(f'/api/courses/{cid}/vivas',json={'title':'Five approved questions','scope':{'resource_ids':[rid]},'config':{'count':5,'total_marks':25,'follow_up_depth':3,'personalize_questions':True,'minutes':1}}),201)
    assert ex['config']['follow_up_depth']==0 and not ex['config']['personalize_questions'] and ex['minutes']==10
    evidence=good(t.post(f'/api/courses/{cid}/material-query',json={'resource_ids':[rid]}))[0]
    prompts=['What is a reliable byte stream?','What is the role of sequence numbers?','Why are acknowledgments used?','Explain retransmission of lost data.','What does ordered delivery mean?']
    for prompt in prompts:
        good(t.post(f"/api/vivas/{ex['id']}/questions",json={'question_text':prompt,'marks':5,'expected_concepts':['Course concept'],'acceptable_answer_points':['Explain using the source.'],'citations':[{'chunk_id':evidence['id'],'quote':evidence['text'][:80]}],'approved':True}),201)
    published=good(t.post(f"/api/vivas/{ex['id']}/publish"))
    return t,s,cid,published,prompts


def test_exact_five_and_teacher_only_final_marks(clients,monkeypatch):
    t,s,cid,ex,prompts=make_five(clients);peer,_=clients('ahmed@campuspath.demo')
    with SessionLocal() as db:code=db.get(Course,cid).enrollment_code
    good(peer.post('/api/courses/join',json={'code':code}))
    calls=[]
    async def fake(q,transcript,history,rubric,sources):
        calls.append((q['question_text'],transcript))
        with SessionLocal() as db:
            assert db.scalar(select(OralResponse.id).where(OralResponse.transcript==transcript)) is not None
        return {'marks':4,'confidence':.9,'correctness':'partially_correct','feedback':'Add the missing explanation.','correct_points':['Core idea'],'incorrect_points':['One incorrect term'],'missing_points':['Justification'],'misconceptions':[],'scoring':[],'follow_up':'A new question not approved by the teacher.'},'AI PROVISIONAL'
    monkeypatch.setattr(grounded,'evaluate',fake)
    a=good(s.post(f"/api/vivas/{ex['id']}/start"));b=good(peer.post(f"/api/vivas/{ex['id']}/start"));sid=a['id']
    assert a['question']==b['question'] and peer.get(f'/api/oral-sessions/{sid}').status_code==404
    for i,prompt in enumerate(prompts):
        assert a['question']['question_text']==prompt and a['index']==i and a['turn']==i and not a['question']['is_follow_up']
        assert 115<a['remaining_seconds']<=120
        a=good(s.post(f'/api/oral-sessions/{sid}/answer',json={'turn':i,'transcript':f'Sample answer {i}'}))
        assert len(a['responses'])==i+1 and a['ai_proposed_marks'] is None
        assert all('evaluation' not in r for r in a['responses'])
    assert a['complete'] and a['status']=='TEACHER_REVIEW_REQUIRED' and 'question' not in a and len(calls)==5
    assert s.post(f'/api/oral-sessions/{sid}/answer',json={'turn':5,'transcript':'Extra answer'}).status_code==409
    review=good(t.get(f'/api/courses/{cid}/oral-review'))
    a=next(row for row in review if row['id']==sid);assert a['ai_proposed_marks']==20
    for q,r in zip(a['questions'],a['responses']):
        assert r['question_id']==q['id'] and r['evaluation']['incorrect_points'] and r['evaluation']['missing_points']
        good(t.put(f"/api/oral-sessions/{sid}/questions/{q['id']}/review",json={'marks':4,'feedback':'Add justification.'}))
    final=good(t.post(f'/api/oral-sessions/{sid}/finalize'));assert final['confirmed_marks']==20
    visible=good(s.get(f'/api/oral-sessions/{sid}'));assert visible['confirmed_marks'] is None and visible['percentage'] is None and visible['reviews']==[]
    assert all('evaluation' not in r and 'proposed_marks' not in r for r in visible['responses'])


def test_server_timeout_draft_and_closed_browser_recovery(clients,monkeypatch):
    t,s,cid,ex,prompts=make_five(clients);clock=[now()];monkeypatch.setattr(formal,'now',lambda:clock[0])
    monkeypatch.setattr(grounded,'enabled',lambda:False)
    a=good(s.post(f"/api/vivas/{ex['id']}/start"));sid=a['id'];first=a['question_deadline']
    clock[0]+=timedelta(seconds=70)
    good(s.put(f'/api/oral-sessions/{sid}/draft',json={'turn':0,'revision':2,'transcript':'Latest partial answer'}))
    good(s.put(f'/api/oral-sessions/{sid}/draft',json={'turn':0,'revision':1,'transcript':'Older stale answer'}))
    r=good(s.get(f'/api/oral-sessions/{sid}'));assert r['draft']=='Latest partial answer' and r['question_deadline']==first and r['remaining_seconds']==50
    clock[0]+=timedelta(seconds=50)
    a=good(s.post(f'/api/oral-sessions/{sid}/answer',json={'turn':0,'transcript':'Late replacement must not be accepted'}))
    assert a['responses'][0]['transcript']=='Latest partial answer' and a['turn']==1 and a['remaining_seconds']==120
    good(s.put(f'/api/oral-sessions/{sid}/draft',json={'turn':1,'revision':1,'transcript':'Another saved partial answer'}))
    clock[0]+=timedelta(seconds=480)
    # The server recovery job advances elapsed questions even without a student request.
    pending,active=formal.collect_due_vivas();assert pending and not active
    a=good(s.get(f'/api/oral-sessions/{sid}'));assert a['complete'] and len(a['responses'])==5
    assert a['responses'][1]['transcript']=='Another saved partial answer'
    assert all(r['transcript']=='' for r in a['responses'][2:])
    review=next(r for r in good(t.get(f'/api/courses/{cid}/oral-review')) if r['id']==sid)
    assert all(r['evaluation']['timed_out'] for r in review['responses'])
    assert all(r['proposed_marks']==0 for r in review['responses'][2:])
    assert s.put(f'/api/oral-sessions/{sid}/draft',json={'turn':4,'revision':5,'transcript':'Too late'}).status_code==409
