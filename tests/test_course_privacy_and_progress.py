"""Two enrolled accounts, official grade visibility and manual curriculum regression."""
from datetime import timedelta
from sqlalchemy import select
from app.db import SessionLocal
from app.models import Course,Topic,QuizRun,Notification,now
from tests.test_private_practice_and_grading import setup_course,good


def test_two_students_same_course_practice_is_private(clients):
    t,a,b,cid,rid=setup_course(clients)
    with SessionLocal() as db:code=db.get(Course,cid).enrollment_code
    good(b.post('/api/courses/join',json={'code':code}))
    aid=good(a.get('/api/auth/me'))['user']['id'];bid=good(b.get('/api/auth/me'))['user']['id']
    progress=lambda client,sid:good(client.get(f'/api/courses/{cid}/students/{sid}/progress'))
    assert progress(a,aid)['quiz_average'] is None and progress(b,bid)['quiz_average'] is None
    quiz=good(a.post(f'/api/courses/{cid}/quiz',json={'material_based':True,'resource_ids':[rid],'count':4}),201)
    with SessionLocal() as db:key=db.get(QuizRun,quiz['id']).settings['practice_questions'][0]['correct']
    good(a.post(f"/api/quiz/{quiz['id']}/answer",json={'question_id':quiz['question']['id'],'selected':key}))
    assert b.get(f"/api/quiz/{quiz['id']}").status_code==404
    assert t.get(f"/api/quiz/{quiz['id']}").status_code==404
    assert b.post(f"/api/quiz/{quiz['id']}/answer",json={'question_id':quiz['question']['id'],'selected':key}).status_code==404
    assert b.get(f'/api/courses/{cid}/students/{aid}/progress').status_code==403
    assert good(b.get(f'/api/courses/{cid}/assessments'))==[]
    assert progress(a,aid)['quiz_average']==100 and progress(a,aid)['attempts']==1
    assert progress(b,bid)['quiz_average'] is None and progress(b,bid)['attempts']==0
    v=good(a.post(f'/api/courses/{cid}/viva/start',json={'material_based':True,'resource_ids':[rid],'count':2}))
    answer=good(a.post(f"/api/viva/{v['id']}/answer",json={'turn_index':0,'text':'A distinctive private response.'}))
    assert b.get(f"/api/viva/{v['id']}").status_code==404
    assert t.get(f"/api/viva/{v['id']}").status_code==404
    assert good(b.get(f'/api/courses/{cid}/viva/history'))==[]
    assert good(t.get(f'/api/courses/{cid}/viva/review'))==[]
    assert t.post(f"/api/viva/turns/{answer['next']['turns'][0]['id']}/review",json={'score':80,'feedback':'Review'}).status_code==403
    assert progress(a,aid)['private_practice']['viva_answers']==1
    assert progress(b,bid)['private_practice']['viva_answers']==0
    assert good(t.get(f'/api/courses/{cid}/topics'))==[]
    assert good(b.get(f'/api/courses/{cid}/material-catalog'))['topics']==[]
    assert progress(t,aid)['attempts']==0 and 'private_practice' not in progress(t,aid)
    assert good(t.get(f'/api/courses/{cid}/analytics'))['mastery'] is None
    assert good(t.get(f'/api/courses/{cid}/research'))['observations']==0
    assert not any(n['target']=='viva-review' for n in good(t.get('/api/notifications')))
    assert b.get(f'/api/courses/{cid}/assessments',headers={'X-Workspace-User':str(aid)}).status_code==409


def test_manual_chapter_graph_and_assigned_results(clients):
    t,a,b,cid,rid=setup_course(clients)
    with SessionLocal() as db:code=db.get(Course,cid).enrollment_code
    good(b.post('/api/courses/join',json={'code':code}))
    aid=good(a.get('/api/auth/me'))['user']['id'];bid=good(b.get('/api/auth/me'))['user']['id']
    src=good(t.post(f'/api/courses/{cid}/material-query',json={'resource_ids':[rid]}))[0]['id']
    first=good(t.post(f'/api/courses/{cid}/topics',json={'name':'Binary search','chapter':'Chapter 7 Search','unit':'Unit 2','source_ids':[src]}),201)['id']
    second=good(t.post(f'/api/courses/{cid}/topics',json={'name':'Merge sort','chapter':'Chapter 8 Sorting','prerequisites':[first]}),201)['id']
    # Retain old internal topics without publishing them in the curriculum.
    with SessionLocal() as db:
        db.add(Topic(course_id=cid,name='Unwanted footer heading',structure={'automatic_material_topic':True}));db.commit()
    rows=good(a.get(f'/api/courses/{cid}/topics'));assert {r['id'] for r in rows}=={first,second}
    assert next(r for r in rows if r['id']==second)['prerequisites']==[first]
    assert next(r for r in rows if r['id']==first)['chapter']=='Chapter 7 Search'
    assert good(a.post(f'/api/courses/{cid}/material-query',json={'chapters':['Chapter 7 Search'],'topic_names':['Binary search']}))[0]['id']==src
    p=good(a.get(f'/api/courses/{cid}/students/{aid}/progress'));assert all(r['mastery'] is None for r in p['topics'])
    assignment=good(t.post(f'/api/courses/{cid}/assignments',json={'title':'Teacher assigned','instructions':'Explain binary search.','rubric':'Correctness','due':(now()+timedelta(days=1)).isoformat(),'source_ids':[src]}),201)['id']
    good(a.post(f'/api/assignments/{assignment}/submit',json={'text':'A distinct answer.'}))
    sub=next(r for r in good(t.get(f'/api/courses/{cid}/assignments')) if r['id']==assignment)['submissions'][0]
    good(t.post(f"/api/submissions/{sub['id']}/grade",json={'grade':85,'feedback':'Good answer.'}))
    assert good(t.get(f'/api/courses/{cid}/students/{aid}/progress'))['assignment_average']==85
    assert good(t.get(f'/api/courses/{cid}/students/{bid}/progress'))['assignment_average'] is None
    assert next(r for r in good(b.get(f'/api/courses/{cid}/assignments')) if r['id']==assignment)['submissions']==[]
    assert next(r for r in good(a.get(f'/api/courses/{cid}/assignments')) if r['id']==assignment)['submissions'][0]['grade'] is None

    assert a.post(f'/api/courses/{cid}/topics/{second}/archive').status_code in (403,404)
    good(t.post(f'/api/courses/{cid}/topics/{second}/archive'))
    assert [r['id'] for r in good(a.get(f'/api/courses/{cid}/topics'))]==[first]
    assert a.get(f'/api/courses/{cid}/topics?include_archived=true').status_code==403
    assert next(r for r in good(t.get(f'/api/courses/{cid}/topics?include_archived=true')) if r['id']==second)['archived']
    good(t.post(f'/api/courses/{cid}/topics/{second}/restore'))
    assert {r['id'] for r in good(a.get(f'/api/courses/{cid}/topics'))}=={first,second}
