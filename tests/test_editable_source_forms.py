"""Typed source selectors remain scoped to actual teacher-provided evidence."""
from app.models import Chunk
from app.db import SessionLocal
from sqlalchemy import select
from tests.test_material_driven_learning import good, new_course, make_slides


def test_typed_chapter_and_topic_names(clients):
    teacher, student, peer, _, _, _, cid = new_course(clients)
    rid=good(teacher.post(f'/api/courses/{cid}/resources',files={'file':('chapter notes.pptx',make_slides())}),201)['id']
    with SessionLocal() as db:
        for ch in db.scalars(select(Chunk).where(Chunk.resource_id==rid)):
            number=int(ch.location.split()[1]);ch.structure={**(ch.structure or {}),'chapter':'2Application' if number<3 else '20','chapter_title':'Chapter 2 Application layer' if number<3 else 'Chapter 20 Graphs'}
        db.commit()
    scope={'resource_ids':[rid],'chapters':['Chapter 2'],'topic_names':['binary-search'],'page_from':2,'page_to':2}
    query=good(student.post(f'/api/courses/{cid}/material-query',json=scope))
    assert query and all(x['location']=='Slide 2' for x in query)
    assert student.post(f'/api/courses/{cid}/material-query',json={**scope,'topic_names':['nonexistent topic']}).status_code==409
    assert student.post(f'/api/courses/{cid}/material-query',json={**scope,'chapters':['Chapter 20']}).status_code==409
    private=good(student.post(f'/api/courses/{cid}/resources',files={'file':('private.txt',b'Binary search private text.')}),201)['id']
    assert student.post(f'/api/courses/{cid}/material-query',json={**scope,'resource_ids':[private]}).status_code==422
    exam=good(teacher.post(f'/api/courses/{cid}/vivas',json={'title':'Typed scope viva','scope':scope,'config':{'count':1,'total_marks':5,'minutes':20,'question_types':['Oral Viva']}}),201)
    assert exam['scope']['topic_names']==['binary-search']
    assert [c['weight'] for c in exam['config']['rubric']]==[50,30,20]
    assert exam['config']['review_required'] and not exam['config']['immediate_feedback']
    viva=good(student.post(f'/api/courses/{cid}/viva/start',json={'resource_ids':[rid],'chapters':['Chapter 2'],'heading':'Binary search','count':1,'material_based':True}))
    assert all(x['location']=='Slide 2' for x in viva['question']['source_locations'])
    tutor=good(student.post(f'/api/courses/{cid}/tutor',json={'question':'Explain binary search','resource_ids':[rid],'chapters':['Chapter 2'],'heading':'Binary search','teacher_only':True}))
    assert tutor['sources'] and all(x['location']=='Slide 2' for x in tutor['sources'])
    assert student.post(f'/api/courses/{cid}/quiz',json={'material_based':True,'resource_ids':[rid],'chapters':['Chapter 20'],'heading':'Binary search','count':1}).status_code==409
