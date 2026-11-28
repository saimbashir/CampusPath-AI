"""Teacher dashboard evidence: assigned work only. Never query personal practice."""
from sqlalchemy import select
from app.models import Topic, Assignment, Submission, VivaExam, OralSession, OralReview, VivaQuestion

def visible_topic(t):
    return not any((t.structure or {}).get(k) for k in ('automatic_material_topic','practice_anchor','archived'))

def avg(values):
    return round(sum(values)/len(values),1) if values else None

def official_snapshot(db,sid,cid):
    topics=[t for t in db.scalars(select(Topic).where(Topic.course_id==cid)) if visible_topic(t)]
    ids={t.id for t in topics}
    grades=list(db.scalars(select(Submission.grade).join(Assignment,Assignment.id==Submission.assignment_id).where(Assignment.course_id==cid,Submission.student_id==sid,Submission.grade.is_not(None))))
    sessions=list(db.scalars(select(OralSession).join(VivaExam,VivaExam.id==OralSession.viva_id).where(VivaExam.course_id==cid,OralSession.student_id==sid,OralSession.status=='FINALIZED')))
    scores=[]; grouped={}; bloom={}; outcomes={}
    for session in sessions:
        rows=db.execute(select(OralReview,VivaQuestion).join(VivaQuestion,VivaQuestion.id==OralReview.question_id).where(OralReview.session_id==session.id,OralReview.finalized.is_(True))).all()
        total=sum(q.marks for r,q in rows)
        if total:scores.append(100*sum(r.marks for r,q in rows)/total)
        for r,q in rows:
            if not q.marks:continue
            value=100*r.marks/q.marks
            if q.topic_id in ids:grouped.setdefault(q.topic_id,[]).append(value)
            bloom.setdefault(q.content.get('bloom','Unmapped'),[]).append(value)
            clo=q.content.get('clo')
            if clo:outcomes.setdefault(clo,[]).append(value)
    data=[{'id':t.id,'name':t.name,'description':t.description,'prerequisites':[p for p in (t.prerequisites or []) if p in ids],'clo':t.clo,'mastery':avg(grouped.get(t.id,[])),'attempts':len(grouped.get(t.id,[])),'confidence':0,'last_practiced':None} for t in topics]
    mean=avg(grades+scores)
    return {'mastery':mean,'readiness':None,'quiz_average':None,'assignment_average':avg(grades),'viva_average':avg(scores),'viva_reviewed_count':len(scores),'attempts':len(grades)+len(scores),'trend':None,'status':'NOT ASSESSED' if mean is None else 'NEEDS SUPPORT' if mean<60 else 'ASSESSED','topics':data,'clos':{k:avg(v) for k,v in outcomes.items()},'bloom':{k:avg(v) for k,v in bloom.items()},'misconceptions':[],'revisions':[],'path':[],'history':[],'study_streak':None,'revision_completion':{'done':0,'pending':0},'readiness_detail':{'score':None,'factors':[],'methodology':'Only teacher-assigned, confirmed grades are visible. Personal learning activity is private.'},'readiness_factors':{'components':[],'coverage':None,'accuracy':None,'methodology':'Assigned work only.'}}
