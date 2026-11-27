"""Regression coverage for material-driven learning and durable student updates."""
from datetime import timedelta
from io import BytesIO
from sqlalchemy import select
from pptx import Presentation
from app.db import SessionLocal
from app.models import Chunk, Notification, Resource, Topic, VivaSession, now


def good(response, code=200):
    assert response.status_code == code, response.text
    return response.json()


def make_slides():
    ppt = Presentation()
    slides = [
        ('Sorting fundamentals', 'Sorting arranges values according to a chosen order. Insertion sort builds a sorted prefix by inserting one element at a time.'),
        ('Binary search', 'Binary search repeatedly halves a sorted search interval. Each comparison eliminates half of the remaining possibilities.'),
        ('Graph traversal', 'Breadth first search explores vertices by distance from the start. A queue stores the vertices that still need exploration.'),
    ]
    for title, body in slides:
        slide = ppt.slides.add_slide(ppt.slide_layouts[1])
        slide.shapes.title.text = title
        slide.placeholders[1].text = body
    stream = BytesIO(); ppt.save(stream); return stream.getvalue()


def new_course(clients):
    teacher, tu = clients('teacher@campuspath.demo')
    student, su = clients('saim@campuspath.demo')
    peer, pu = clients('ahmed@campuspath.demo')
    course = good(teacher.post('/api/courses', json={'name':'Material-driven course','code':'MDL','section':'A'}), 201)
    cid = course['id']
    good(student.post('/api/courses/join', json={'code':course['enrollment_code']}))
    return teacher, student, peer, su, pu, course, cid


def test_slides_work_without_manual_concepts_and_legacy_metadata(clients):
    teacher, student, peer, su, pu, course, cid = new_course(clients)
    data = make_slides()
    rid = good(teacher.post(f'/api/courses/{cid}/resources', files={'file':('lecture.pptx', data)}), 201)['id']
    assert good(teacher.get(f'/api/courses/{cid}/topics')) == []
    # Simulate PPTX chunks indexed before slide-position metadata was introduced.
    with SessionLocal() as db:
        for ch in db.scalars(select(Chunk).where(Chunk.resource_id == rid)):
            ch.structure = {'book':'lecture.pptx', 'page':None}
        db.commit()
        assert db.scalar(select(Notification).where(Notification.user_id==su['id'],Notification.event_key==f'material:{rid}')) is not None
        assert db.scalar(select(Notification).where(Notification.user_id==pu['id'],Notification.event_key==f'material:{rid}')) is None
    catalog = good(student.get(f'/api/courses/{cid}/material-catalog'))
    assert catalog['resources'][0]['chunks'][1]['structure']['slide']==2
    scoped = good(student.post(f'/api/courses/{cid}/material-query',json={'resource_ids':[rid], 'page_from':2,'page_to':2}))
    assert scoped and all(s['location']=='Slide 2' for s in scoped)
    assert all('Binary search' in s['text'] for s in scoped)
    tutor = good(student.post(f'/api/courses/{cid}/tutor',json={'question':'Explain slide 2','teacher_only':True,'resource_ids':[rid]}))
    assert tutor['sources'] and all(s['location']=='Slide 2' for s in tutor['sources'])
    private = good(student.post(f'/api/courses/{cid}/resources',files={'file':('private.txt',b'PrivateRareToken is a student-only note.')}),201)['id']
    assert good(student.post(f'/api/courses/{cid}/tutor',json={'question':'PrivateRareToken','teacher_only':True}))['sources']==[]
    assert student.post(f'/api/courses/{cid}/viva/start',json={'resource_ids':[private],'count':1}).status_code==422
    session = good(student.post(f'/api/courses/{cid}/viva/start',json={'material_based':True,'resource_ids':[rid],'page_from':2,'page_to':2,'count':3,'language':'Roman Urdu'}))
    assert session['material_based'] and session['total']==3
    assert all(s['location']=='Slide 2' for s in session['question']['source_locations'])
    assert session['question']==good(student.get(f"/api/viva/{session['id']}"))['question']
    assert peer.get(f"/api/viva/{session['id']}").status_code==404
    answer = good(student.post(f"/api/viva/{session['id']}/answer",json={'turn_index':0,'text':'Binary search interval ko half karta hai.'}))
    assert answer['proposed_score'] is None and answer['next']['index']==1
    assert answer['evaluation']['sources'][0]['location']=='Slide 2'
    assert good(teacher.get(f'/api/courses/{cid}/viva/review'))==[]
    assert student.get(f'/api/courses/{cid}/resources/{rid}/download').content==data
    # Teacher can create formal assessments and assignments without manual concepts.
    exam = good(teacher.post(f'/api/courses/{cid}/vivas',json={'title':'Slide two viva','scope':{'resource_ids':[rid],'page_from':2,'page_to':2},'config':{'count':1,'total_marks':5}}),201)
    assert exam['scope']['page_from']==2
    aid=good(teacher.post(f'/api/courses/{cid}/assignments',json={'title':'Slide two assignment','instructions':'Explain binary search.','rubric':'Use course evidence.','due':(now()+timedelta(days=2)).isoformat(),'scope':{'resource_ids':[rid],'heading':'Binary search'}}),201)['id']
    assignment=next(a for a in good(student.get(f'/api/courses/{cid}/assignments')) if a['id']==aid)
    assert assignment['source_ids']==[s['id'] for s in scoped]
    with SessionLocal() as db:
        assert db.scalar(select(Notification).where(Notification.user_id==su['id'],Notification.event_key==f'assignment-new:{aid}')) is not None
        assert db.scalar(select(Notification).where(Notification.user_id==su['id'],Notification.event_key==f'viva-published:{exam["id"]}')) is None
    source=scoped[0]
    good(teacher.post(f"/api/vivas/{exam['id']}/questions",json={'question_text':'Explain how binary search narrows its interval.','marks':5,'expected_concepts':['Halving'],'acceptable_answer_points':['Each comparison eliminates half of the possibilities.'],'citations':[{'chunk_id':source['id'],'quote':source['text']}],'approved':True}),201)
    good(teacher.post(f"/api/vivas/{exam['id']}/publish"))
    with SessionLocal() as db:
        assert db.scalar(select(Notification).where(Notification.user_id==su['id'],Notification.event_key==f'viva-published:{exam["id"]}')) is not None
    # Joining later catches up immediately, while unrelated courses remain private.
    good(peer.post('/api/courses/join',json={'code':course['enrollment_code']}))
    first = good(peer.get('/api/notifications'))
    assert any(n['course_id']==cid and n['title']=='New course material' for n in first)
    assert not any('private.txt' in n['message'] for n in first)
    assert {n['id'] for n in first}=={n['id'] for n in good(peer.get('/api/notifications'))}


def test_uploaded_not_indexed_has_accurate_status_and_file_access(clients):
    teacher,student,peer,su,pu,course,cid=new_course(clients)
    from app.models import ResourceBlob
    with SessionLocal() as db:
        row=Resource(course_id=cid,owner_id=None,filename='processing.pptx',kind='COURSE MATERIAL',status='processing')
        db.add(row);db.flush();rid=row.id;db.add(ResourceBlob(resource_id=rid,data=b'example',content_type='application/octet-stream'));db.commit()
    catalog=good(student.get(f'/api/courses/{cid}/material-catalog'))
    assert not catalog['resources'] and catalog['unready_resources'][0]['status']=='processing'
    response=student.post(f'/api/courses/{cid}/viva/start',json={'resource_ids':[rid],'count':1})
    assert response.status_code==409 and 'index' in response.json()['detail']
    assert student.get(f'/api/courses/{cid}/resources/{rid}/download').content==b'example'
    assert any(n['title']=='New course material uploaded' for n in good(student.get('/api/notifications')))


def test_generate_assessment_and_ai_practice_without_topics(clients,monkeypatch):
    teacher,student,peer,su,pu,course,cid=new_course(clients)
    rid=good(teacher.post(f'/api/courses/{cid}/resources',files={'file':('lecture.pptx',make_slides())}),201)['id']
    from app.ai import grounded
    from app.api import viva
    from app.ai.viva import VivaEvaluation
    async def questions(evidence,topics,config,existing_prompts=None):
        assert evidence and all(s['resource_id']==rid and s['location']=='Slide 2' for s in evidence)
        assert topics==[]
        source=evidence[0];citation=grounded.Citation(chunk_id=source['id'],quote=source['text'][:1000])
        return [grounded.GroundedQuestion(question_text=f'Explain binary search relationship {i+1}.',question_type='MCQ' if config['question_types']==['MCQ'] else 'Oral Viva',expected_concepts=['Halving'],acceptable_answer_points=['Sorted search interval is halved.'],citations=[citation],options=['Halves interval','Doubles interval'] if config['question_types']==['MCQ'] else [],correct_option=0 if config['question_types']==['MCQ'] else None) for i in range(config['count'])], 'AI GROUNDED'
    monkeypatch.setattr(grounded,'enabled',lambda:True)
    monkeypatch.setattr(grounded,'questions',questions)
    assert good(teacher.get(f'/api/courses/{cid}/topics'))==[]
    draft=good(teacher.post(f'/api/courses/{cid}/questions/generate-batch',json={'resource_ids':[rid],'page_from':2,'page_to':2,'count':4}),201)
    assert draft['created']==4
    assert all(q['source_ids'] and not q['approved'] for q in good(teacher.get(f'/api/courses/{cid}/questions')))
    session=good(student.post(f'/api/courses/{cid}/viva/start',json={'resource_ids':[rid],'page_from':2,'page_to':2,'count':2}))
    assert session['question']['provider']=='AI GROUNDED'
    async def evaluator(prompt,answer,topic,sources,language):
        assert sources and all(x['location']=='Slide 2' for x in sources)
        return VivaEvaluation(score=80,concept_coverage=['Halving'],missing_information=['Sorted interval'],possible_misconceptions=[],feedback='Correct. Remember the interval is sorted.',follow_up='Why must the interval be sorted?',confidence=.9)
    monkeypatch.setattr(viva,'DEMO_MODE',False);monkeypatch.setenv('LLM_API_KEY','fake-test-key');monkeypatch.setattr(viva,'evaluate_material',evaluator)
    response=good(student.post(f"/api/viva/{session['id']}/answer",json={'turn_index':0,'text':'It halves the interval.'}))
    assert response['status']=='AI PRACTICE' and response['proposed_score']==80