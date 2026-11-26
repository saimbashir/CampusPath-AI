from datetime import timedelta
from app.db import SessionLocal
from app.models import VivaExam,now


def test_student_course_updates_and_isolation(clients):
    t,tu=clients('teacher@campuspath.demo');s,su=clients('saim@campuspath.demo');other,ou=clients('ahmed@campuspath.demo')
    c=t.post('/api/courses',json={'name':'Updates Test','code':'UPD','section':'A'}).json();cid=c['id'];assert s.post('/api/courses/join',json={'code':c['enrollment_code']}).status_code==200
    r=t.post(f'/api/courses/{cid}/resources',files={'file':('new-lecture.txt',b'Breadth first search explores nodes level by level.')});assert r.status_code==201,r.text;rid=r.json()['id']
    r=s.post(f'/api/courses/{cid}/resources',files={'file':('private-notes.txt',b'Private student notes.')});assert r.status_code==201
    assert t.post(f'/api/courses/{cid}/assignments',json={'title':'Future homework','instructions':'Explain breadth first search','rubric':'Correct reasoning','due':(now()+timedelta(days=10)).isoformat()}).status_code==201
    assert t.post(f'/api/courses/{cid}/assignments',json={'title':'Soon homework','instructions':'Explain breadth first search','rubric':'Correct reasoning','due':(now()+timedelta(days=1)).isoformat()}).status_code==201
    # Seed explicit publication states independently of generation; existing formal-viva tests cover publication.
    with SessionLocal() as db:
        for title,status,ids in [('Published viva','PUBLISHED',[su['id']]),('Draft secret','DRAFT',[]),('Other student viva','PUBLISHED',[ou['id']])]:
            db.add(VivaExam(course_id=cid,teacher_id=tu['id'],title=title,status=status,config={'student_ids':ids,'ends':(now()+timedelta(hours=12)).isoformat()},scope={}))
        db.commit()
    assert s.get(f'/api/courses/{cid}/resources/{rid}/download').content==b'Breadth first search explores nodes level by level.'
    assert other.get(f'/api/courses/{cid}/resources/{rid}/download').status_code in (403,404)
    resources=s.get(f'/api/courses/{cid}/resources').json();assert any(r['id']==rid and r['download_available'] for r in resources)
    tutor=s.post(f'/api/courses/{cid}/tutor',json={'question':'Explain breadth first search'});assert tutor.status_code==200,tutor.text;assert any(x['filename']=='new-lecture.txt' for x in tutor.json()['sources'])
    first=[n for n in s.get('/api/notifications').json() if n['course_id']==cid];messages=' '.join(n['message'] for n in first)
    for name in ['new-lecture.txt','Future homework','Soon homework','Published viva']:assert name in messages
    for name in ['private-notes.txt','Draft secret','Other student viva']:assert name not in messages
    assert any(n['title']=='Viva due soon' for n in first);assert any(n['title']=='Assignment due soon' for n in first)
    assert not any(n['course_id']==cid for n in other.get('/api/notifications').json())
    nid=first[0]['id'];assert s.post(f'/api/notifications/{nid}/read').status_code==200
    second=[n for n in s.get('/api/notifications').json() if n['course_id']==cid];assert {n['id'] for n in first}=={n['id'] for n in second};assert next(n for n in second if n['id']==nid)['read']