"""Regression checks for per-student viva variation and question-bank integrity."""
from app.ai.viva_variation import PATTERNS,prompt_for_turn
from tests.test_workflows import good
from tests.test_universal_viva import course_flow,MATERIALS


def test_thirty_styles_are_unique_and_session_prompts_are_stable():
    assert len(PATTERNS)==30
    p=[prompt_for_turn(10,2,1,i,'Binary Search') for i in range(30)]
    assert len({style for style,_ in p})==30
    assert len({text for _,text in p})==30
    assert p==[prompt_for_turn(10,2,1,i,'Binary Search') for i in range(30)]
    another=[prompt_for_turn(11,3,1,i,'Binary Search') for i in range(30)]
    assert p!=another


def test_student_practice_has_30_distinct_prompts_and_resume_persists(clients):
    student,_=clients('saim@campuspath.demo')
    another,_=clients('ahmed@campuspath.demo')
    first=good(student.post('/api/courses/1/viva/start',json={'topic_id':7,'count':30}))
    second=good(another.post('/api/courses/1/viva/start',json={'topic_id':7,'count':30}))
    assert first['total']==30 and second['total']==30
    assert first['question']['prompt']!=second['question']['prompt']
    assert first['question']==good(student.get(f"/api/viva/{first['id']}"))['question']
    seen={(first['question']['style'],first['question']['prompt'])}
    for i in range(30):
        result=good(student.post(f"/api/viva/{first['id']}/answer",json={'turn_index':i,'text':'My course-based answer is submitted for teacher review.'}))
        if i<29:
            question=result['next']['question']
            assert (question['style'],question['prompt']) not in seen
            seen.add((question['style'],question['prompt']))
    assert result['next']['complete'] and len(result['next']['turns'])==30


def test_formal_question_pool_requires_exact_approved_set(clients):
    teacher,student,cid,rid,_=course_flow(clients,*MATERIALS[1])
    peer,_=clients('ahmed@campuspath.demo')
    # Enroll the second student using teacher-issued enrollment code.
    from sqlalchemy import select
    from app.db import SessionLocal
    from app.models import Course
    with SessionLocal() as db: code=db.get(Course,cid).enrollment_code
    good(peer.post('/api/courses/join',json={'code':code}))
    ex=good(teacher.post(f'/api/courses/{cid}/vivas',json={'title':'Individual oral exams','scope':{'resource_ids':[rid]},'config':{'count':2,'total_marks':10,'personalize_questions':True}}),201)
    evidence=good(teacher.post(f'/api/courses/{cid}/material-query',json={'resource_ids':[rid]}))[0]
    created=[]
    for i in range(7):
        q={'question_text':f'Explain part {i+1} of the concept using the provided notes.', 'marks':5,
           'expected_concepts':['The course material'], 'acceptable_answer_points':['Explain correctly'],
           'citations':[{'chunk_id':evidence['id'],'quote':evidence['text']}], 'approved':True}
        created.append(good(teacher.post(f"/api/vivas/{ex['id']}/questions",json=q),201))
    assert teacher.post(f"/api/vivas/{ex['id']}/publish").status_code==409
    for q in created[-1]['questions'][2:]:good(teacher.post(f"/api/vivas/{ex['id']}/questions/{q['id']}/review",json={'approved':False}))
    published=good(teacher.post(f"/api/vivas/{ex['id']}/publish"))
    assert published['count']==2 and len([q for q in published['questions'] if q['approved']])==2
    a=good(student.post(f"/api/vivas/{ex['id']}/start"))
    b=good(peer.post(f"/api/vivas/{ex['id']}/start"))
    assert a['total']==2 and b['total']==2
    refreshed=good(student.get(f"/api/oral-sessions/{a['id']}"));assert a['id']==refreshed['id'] and a['question']==refreshed['question'] and a['question_deadline']==refreshed['question_deadline']
    for row in (a,b):
        assert 'expected_concepts' not in str(row)
        assert row['question']['id'] in [x['id'] for x in published['questions']]
    # Individual session IDs are persisted; a student's exam cannot change on refresh.
    with SessionLocal() as db:
        from app.models import OralSession
        x=db.get(OralSession,a['id']); y=db.get(OralSession,b['id'])
        assert len(x.question_ids)==len(y.question_ids)==2
        assert len(set(x.question_ids))==2
        assert x.question_ids==y.question_ids==[q['id'] for q in published['questions'] if q['approved']]
