from datetime import timedelta
from app.models import now, Question, QuizRun, Answer
from app.db import SessionLocal
from sqlalchemy import select,func
from app.ai import grounded,assignment_review


def good(r,code=200):
    assert r.status_code==code,r.text
    return r.json()


def setup_course(clients):
    t,_=clients('teacher@campuspath.demo');s,_=clients('saim@campuspath.demo');peer,_=clients('ahmed@campuspath.demo')
    c=good(t.post('/api/courses',json={'name':'Sample algorithms','code':'PRA','section':'A'}),201)
    good(s.post('/api/courses/join',json={'code':c['enrollment_code']}))
    source=b'Binary search is a method that halves a sorted interval.\nInsertion sort is a method that inserts each element into the sorted prefix.\nBreadth-first search is a method that visits vertices by increasing distance.\nDepth-first search is a method that explores a branch before backtracking.\nMerge sort is a method that combines two sorted sequences.'
    r=good(t.post(f"/api/courses/{c['id']}/resources",files={'file':('lecture.txt',source)}),201)
    return t,s,peer,c['id'],r['id']


def test_personal_quiz_without_approved_bank(clients):
    t,s,peer,cid,rid=setup_course(clients)
    assert good(t.get(f'/api/courses/{cid}/topics'))==[]
    q=good(s.post(f'/api/courses/{cid}/quiz',json={'material_based':True,'resource_ids':[rid],'count':4}),201)
    assert q['total']==4 and len(q['question']['options'])==4 and 'correct' not in q['question']
    assert peer.get(f"/api/quiz/{q['id']}").status_code==404
    with SessionLocal() as db:
        run=db.get(QuizRun,q['id']);key=run.settings['practice_questions'][0]['correct']
    r=good(s.post(f"/api/quiz/{q['id']}/answer",json={'question_id':q['question']['id'],'selected':key}))
    assert r['correct'] and r['sources'][0]['filename']=='lecture.txt' and r['next']['index']==1
    assert s.post(f"/api/quiz/{q['id']}/answer",json={'question_id':q['question']['id'],'selected':key}).status_code==409
    final=good(s.post(f"/api/quiz/{q['id']}/finish"));assert final['score']==25 and final['unanswered']==3
    with SessionLocal() as db:
        assert db.scalar(select(func.count(Question.id)).where(Question.course_id==cid))==0
        assert db.scalar(select(func.count(Answer.id)).where(Answer.run_id==q['id']))==0
    private=good(s.post(f'/api/courses/{cid}/resources',files={'file':('private.txt',b'A private student document.')}),201)
    assert s.post(f'/api/courses/{cid}/quiz',json={'material_based':True,'resource_ids':[private['id']]}).status_code==422


def test_assignment_proposal_teacher_only(clients,monkeypatch):
    t,s,peer,cid,rid=setup_course(clients)
    source=good(t.post(f'/api/courses/{cid}/material-query',json={'resource_ids':[rid]}))[0]
    aid=good(t.post(f'/api/courses/{cid}/assignments',json={'title':'Explain search','instructions':'Describe binary search.','rubric':'Concept 100%.','due':(now()+timedelta(days=1)).isoformat(),'source_ids':[source['id']]}),201)['id']
    async def fake(*args):
        context=args[1][0];src=context['course_sources'][0]
        return assignment_review.AssignmentEvaluation(sufficient_evidence=True,confidence=.9,criteria=[{'name':'Concept','maximum':100,'earned':75,'reason':'Correct method, missing sorted interval condition.'}],correct_points=['Halving'],incorrect_points=[],missing_points=['Sorted interval'],feedback='State the sorted input requirement.',citations=[{'chunk_id':src['id'],'quote':'Binary search is a method that halves a sorted interval.'}])
    monkeypatch.setattr(grounded,'enabled',lambda:True);monkeypatch.setattr(assignment_review,'structured_generation',fake)
    result=good(s.post(f'/api/assignments/{aid}/submit',json={'text':'Binary search halves the interval.'}));assert 'proposal' not in result
    row=good(t.get(f'/api/courses/{cid}/assignments'))[0]['submissions'][0]
    assert row['proposal']['proposed_grade']==75 and row['proposal']['criteria'][0]['deducted']==25 and row['grade'] is None
    sid=row['id'];assert s.post(f'/api/submissions/{sid}/evaluate').status_code==404
    assert peer.get(f'/api/courses/{cid}/assignments').status_code==404
    assert good(s.get(f'/api/courses/{cid}/assignments'))[0]['submissions'][0]['proposal'] is None
    good(t.post(f'/api/submissions/{sid}/grade',json={'grade':80,'feedback':'Explain the sorted input condition.'}))
    student=good(s.get(f'/api/courses/{cid}/assignments'))[0]['submissions'][0]
    assert student['grade'] is None and student['graded'] and student['feedback']=='' and student['proposal'] is None
    teacher=good(t.get(f'/api/courses/{cid}/assignments'))[0]['submissions'][0]
    assert teacher['grade']==80 and teacher['proposal']['proposed_grade']==75


def test_live_practice_uses_selected_sources_without_publishing(clients,monkeypatch):
    t,s,peer,cid,rid=setup_course(clients)
    seen=[]
    async def fake(evidence,topics,config,**kwargs):
        seen.extend(evidence);src=evidence[0]
        assert config['count']==2 and config['question_types']==['MCQ'] and config['difficulty']=='2'
        return [grounded.GroundedQuestion(question_text=prompt,question_type='MCQ',marks=1,difficulty=2,expected_concepts=['Binary search'],acceptable_answer_points=['Binary search halves a sorted interval.'],citations=[{'chunk_id':src['id'],'quote':'Binary search is a method that halves a sorted interval.'}],options=['Binary search','Insertion sort','Breadth-first search','Merge sort'],correct_option=0) for prompt in ('Which method halves a sorted search interval?','Which approach requires a sorted interval and halves it?')], 'AI GROUNDED'
    monkeypatch.setattr(grounded,'enabled',lambda:True);monkeypatch.setattr(grounded,'questions',fake)
    r=good(s.post(f'/api/courses/{cid}/quiz',json={'material_based':True,'resource_ids':[rid],'count':2,'difficulty':2}),201)
    assert r['provider']=='AI GROUNDED' and r['total']==2 and all(src['filename']=='lecture.txt' for src in seen)
    with SessionLocal() as db:assert db.scalar(select(func.count(Question.id)).where(Question.course_id==cid))==0


def test_invalid_assignment_citation_does_not_invent_grade(clients,monkeypatch):
    t,s,peer,cid,rid=setup_course(clients)
    aid=good(t.post(f'/api/courses/{cid}/assignments',json={'title':'Explain sorting','instructions':'Explain merge sort.','rubric':'Concept 100%.','due':(now()+timedelta(days=1)).isoformat()}),201)['id']
    async def fake(*args):
        return assignment_review.AssignmentEvaluation(sufficient_evidence=True,confidence=.9,criteria=[{'name':'Concept','maximum':100,'earned':90,'reason':'Claimed support.'}],correct_points=['Claimed support'],incorrect_points=[],missing_points=[],feedback='Review the method.',citations=[{'chunk_id':99999999,'quote':'Invented source quotation'}])
    monkeypatch.setattr(grounded,'enabled',lambda:True);monkeypatch.setattr(assignment_review,'structured_generation',fake)
    good(s.post(f'/api/assignments/{aid}/submit',json={'text':'A sample answer.'}))
    row=good(t.get(f'/api/courses/{cid}/assignments'))[0]['submissions'][0]
    assert row['grade'] is None and row['proposal']['proposed_grade'] is None
    assert row['proposal']['status']=='TEACHER REVIEW REQUIRED'
