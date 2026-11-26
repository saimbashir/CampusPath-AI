from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from datetime import datetime,timedelta,timezone
from app.models import Notification,Enrollment,Revision,Topic,Assignment,Submission,Question,Course,Resource,VivaExam,OralSession,now
from app.auth.security import teacher_courses

def notify(db,uid,cid,key,title,message,target):
    if db.scalar(select(Notification.id).where(Notification.user_id==uid,Notification.event_key==key)):return
    try:
        with db.begin_nested():db.add(Notification(user_id=uid,course_id=cid,event_key=key,title=title,message=message,target=target))
    except IntegrityError:pass

def _utc(value):
    if not value:return None
    try:
        dt=datetime.fromisoformat(value.replace('Z','+00:00')) if isinstance(value,str) else value
        return dt.astimezone(timezone.utc).replace(tzinfo=None) if dt.tzinfo else dt
    except (ValueError,TypeError,AttributeError):return None


def refresh_course_updates(db,user,cids):
    """Discover durable inbox events on the next inbox check, including for late joiners.
    Only enrolled-course teacher resources, visible assignments and published assigned vivas.
    No private uploads, drafts or other students' assessments are disclosed.
    """
    if not cids:return
    known=set(db.scalars(select(Notification.event_key).where(Notification.user_id==user.id)))
    def add(cid,key,title,message,target):
        if key not in known:
            notify(db,user.id,cid,key,title,message,target)
            known.add(key)
    current=now()
    for rid,cid,filename,course_name in db.execute(select(Resource.id,Resource.course_id,Resource.filename,Course.name).join(Course,Course.id==Resource.course_id).where(Resource.course_id.in_(cids),Resource.owner_id.is_(None),Resource.kind=='COURSE MATERIAL',Resource.status=='ready')):
        add(cid,f'material:{rid}','New course material',f'{course_name}: {filename} is ready to read. Open Materials to access the file.','materials')
    submitted=set(db.scalars(select(Submission.assignment_id).where(Submission.student_id==user.id)))
    for a,course_name,material_only in db.execute(select(Assignment,Course.name,Course.material_only).join(Course,Course.id==Assignment.course_id).where(Assignment.course_id.in_(cids),Assignment.due>=current)):
        if a.id in submitted or (material_only and not a.source_ids):continue
        due=a.due.strftime('%Y-%m-%d %H:%M UTC')
        add(a.course_id,f'assignment-new:{a.id}','New assignment',f'{course_name}: {a.title}. Due {due}.','assignments')
        if a.due<=current+timedelta(days=3):
            add(a.course_id,f'assignment:{a.id}','Assignment due soon',f'{course_name}: {a.title} is due {due}.','assignments')
    sessions=dict(db.execute(select(OralSession.viva_id,OralSession.status).where(OralSession.student_id==user.id)).all())
    for ex,course_name in db.execute(select(VivaExam,Course.name).join(Course,Course.id==VivaExam.course_id).where(VivaExam.course_id.in_(cids),VivaExam.status=='PUBLISHED')):
        cfg=ex.config or {};assigned=cfg.get('student_ids') or []
        if assigned and user.id not in assigned:continue
        if ex.id in sessions and sessions[ex.id]!='IN_PROGRESS':continue
        starts,ends=_utc(cfg.get('starts')),_utc(cfg.get('ends'))
        if ends and ends<current:continue
        window=(' Opens '+starts.strftime('%Y-%m-%d %H:%M UTC')+'.' if starts else '')+(' Due '+ends.strftime('%Y-%m-%d %H:%M UTC')+'.' if ends else '')
        add(ex.course_id,f'viva-published:{ex.id}','New assigned viva',f'{course_name}: {ex.title}.{window}','formal-viva')
        if ends and ends<=current+timedelta(days=1):
            add(ex.course_id,f'viva-due:{ex.id}','Viva due soon',f'{course_name}: {ex.title} closes {ends.strftime("%Y-%m-%d %H:%M UTC")}.','formal-viva')


def refresh(db,user):
    if user.role=='student':
        cids=list(db.scalars(select(Enrollment.course_id).where(Enrollment.student_id==user.id)))
        due=db.execute(select(Revision,Topic).join(Topic,Revision.topic_id==Topic.id).where(Revision.student_id==user.id,Topic.course_id.in_(cids),Revision.done.is_(False),Revision.due<=now()+timedelta(days=1))).all()
        for r,t in due:notify(db,user.id,t.course_id,f'review:{r.id}:{r.due.isoformat()}',f'Review {t.name}','A scheduled revision is due within one day or is overdue.','planner')
        refresh_course_updates(db,user,cids)
    elif user.role=='teacher':
        for q in db.scalars(select(Question).where(Question.course_id.in_(teacher_courses(user)),Question.approved.is_(False))):
            notify(db,user.id,q.course_id,f'question:{q.id}','Question awaiting review',q.prompt[:180],'questions')
        from app.models import VivaSession,VivaTurn
        for turn,session in db.execute(select(VivaTurn,VivaSession).join(VivaSession,VivaSession.id==VivaTurn.session_id).where(VivaSession.course_id.in_(teacher_courses(user)),VivaTurn.reviewed_at.is_(None))):
            notify(db,user.id,session.course_id,f'viva:{turn.id}','Viva response awaiting review','Review the transcript and rubric before confirming the score.','viva-review')
        from app.models import OralSession,VivaExam
        for session,exam in db.execute(select(OralSession,VivaExam).join(VivaExam,VivaExam.id==OralSession.viva_id).where(VivaExam.course_id.in_(teacher_courses(user)),OralSession.status=='TEACHER_REVIEW_REQUIRED')):
            notify(db,user.id,exam.course_id,f'oral-review:{session.id}','Viva ready for marking',exam.title+' has a submitted session awaiting confirmation.','oral-review')
    db.commit()
