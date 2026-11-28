"""Material-grounded formal oral/written assessments with immutable publication and review."""
from datetime import datetime,timedelta
from collections import defaultdict,Counter
import asyncio
import logging
from fastapi import APIRouter,Depends,HTTPException,BackgroundTasks
from pydantic import Field,model_validator
from sqlalchemy import select,update,or_
from app.services.official_progress import visible_topic
from app.db import get_db,SessionLocal
from app.models import VivaExam,VivaQuestion,OralSession,OralResponse,OralReview,Topic,User,Mastery,Revision,Enrollment,now
from app.schemas import Input
from app.auth.security import current_user,course_access,role,audit,throttle
from app.services.materials import MaterialScope,resolve,validate_citations
from app.services.planning import utc_naive
from app.services.notifications import notify
from app.ai import grounded
from app.mastery.engine import update_mastery,revision_dates
router=APIRouter(prefix='/api')
QUESTION_SECONDS=120
log=logging.getLogger("campuspath.formal_viva")
class VivaConfig(Input):
    count:int=Field(default=5,ge=1,le=30)
    total_marks:float=Field(default=25,gt=0,le=1000)
    minutes:int=Field(default=20,ge=1,le=180)
    difficulty:str=Field(default='Mixed',pattern='^(Mixed|1|2|3)$')
    follow_up_depth:int=Field(default=0,ge=0,le=3)
    immediate_feedback:bool=True
    review_required:bool=True
    question_review_required:bool=True
    show_topic:bool=True
    personalize_questions:bool=False
    starts:datetime|None=None
    ends:datetime|None=None
    student_ids:list[int]=Field(default_factory=list,max_length=1000)
    bloom_distribution:dict[str,int]=Field(default_factory=dict)
    question_types:list[str]=Field(default_factory=lambda:['Oral Viva'],max_length=14)
    rubric:list[grounded.RubricCriterion]=Field(default_factory=lambda:[grounded.RubricCriterion(**c) for c in grounded.DEFAULT_RUBRIC],min_length=1,max_length=12)
    @model_validator(mode='after')
    def valid(self):
        if abs(self.total_marks*100-round(self.total_marks*100))>.0001 or self.total_marks*100<self.count:raise ValueError('Use marks with at most two decimal places and at least 0.01 per question.')
        if abs(sum(r.weight for r in self.rubric)-100)>.001 or len({r.name for r in self.rubric})!=len(self.rubric):raise ValueError('Distinct rubric criteria must total 100%.')
        if self.starts:self.starts=utc_naive(self.starts)
        if self.ends:self.ends=utc_naive(self.ends)
        if self.starts and self.ends and self.ends<=self.starts:raise ValueError('End must be after start.')
        levels={'Remember','Understand','Apply','Analyze','Evaluate','Create'}
        if self.bloom_distribution and (set(self.bloom_distribution)-levels or sum(self.bloom_distribution.values())!=100 or any(v<0 for v in self.bloom_distribution.values())):raise ValueError('Known Bloom percentages must total 100.')
        allowed={'Oral Viva','MCQ','True/False','Short Answer','Long Answer','Numerical','Problem Solving','Scenario-Based','Conceptual','Definition','Comparison','Programming Question','Application Question','Analysis Question'}
        if not self.question_types or not set(self.question_types)<=allowed:raise ValueError('Select supported question types.')
        # The formal assessment contract is fixed, regardless of older clients.
        self.follow_up_depth=0;self.personalize_questions=False;self.minutes=self.count*2
        self.question_review_required=True;self.review_required=True;self.immediate_feedback=False
        return self
class CreateViva(Input):
    title:str=Field(min_length=3,max_length=180)
    scope:MaterialScope=Field(default_factory=MaterialScope)
    config:VivaConfig=Field(default_factory=VivaConfig)
class AddQuestion(grounded.GroundedQuestion):
    approved:bool=False
class PublishQuestion(Input):approved:bool
class OralAnswer(Input):
    turn:int=Field(ge=0)
    transcript:str=Field(default="",max_length=12000)
class OralDraft(OralAnswer):
    revision:int=Field(ge=1,le=2147483647)
class ReviewMarks(Input):
    marks:float=Field(ge=0,le=1000)
    feedback:str=Field(min_length=3,max_length=4000)
    flagged:bool=False

def exam_access(db,user,eid,teacher=False):
    ex=db.get(VivaExam,eid)
    if not ex:raise HTTPException(404,'Viva not found.')
    course_access(db,user,ex.course_id,teacher)
    if user.role=='student' and (ex.status!='PUBLISHED' or (ex.config.get('student_ids') and user.id not in ex.config['student_ids'])):raise HTTPException(404,'Viva not assigned.')
    return ex

def session_access(db,user,sid,teacher=False):
    s=db.get(OralSession,sid)
    if not s:raise HTTPException(404,'Session not found.')
    ex=exam_access(db,user,s.viva_id,teacher)
    if not teacher and s.student_id!=user.id:raise HTTPException(404,'Session not found.')
    return s,ex

def evidence_for(db,ex):
    return resolve(db,ex.course_id,MaterialScope.model_validate(ex.scope))

def teacher_question(q):return {'id':q.id,'approved':q.approved,**{k:v for k,v in q.content.items() if k!='sources'},'question_text':q.prompt,'marks':q.marks,'topic_id':q.topic_id,'sources':q.content.get('sources',[])}

def exam_payload(db,ex,teacher=False):
    conf=ex.config
    result={'id':ex.id,'course_id':ex.course_id,'title':ex.title,'status':ex.status,'count':conf['count'],'total_marks':conf['total_marks'],'minutes':conf['count']*2,'starts':conf.get('starts'),'ends':conf.get('ends'),'review_required':True,'immediate_feedback':False,'personalize_questions':False,'created':ex.created}
    if teacher:result.update(scope=ex.scope,config=conf,questions=[teacher_question(q) for q in db.scalars(select(VivaQuestion).where(VivaQuestion.viva_id==ex.id).order_by(VivaQuestion.id))])
    return result

def latest_responses(db,s):
    records=db.scalars(select(OralResponse).where(OralResponse.session_id==s.id).order_by(OralResponse.turn)).all()
    return records,{r.question_id:r for r in records}

def notify_formal_review(db,s,ex):
    from app.models import Course,TeacherAssignment
    recipients={db.get(Course,ex.course_id).teacher_id}|set(db.scalars(select(TeacherAssignment.teacher_id).where(TeacherAssignment.course_id==ex.course_id)))
    for uid in recipients:notify(db,uid,ex.course_id,f'oral-review:{s.id}','Viva ready for marking',ex.title+' has a submitted session awaiting confirmation.','oral-review')

def clock_state(deadline,draft='',revision=0):
    # Reuse the existing JSON field; no database migration or history deletion.
    return {'fixed_viva':True,'deadline':deadline.isoformat(),'draft':draft,'revision':revision}

def locked_session(db,sid):
    return db.scalar(select(OralSession).where(OralSession.id==sid).with_for_update().execution_options(populate_existing=True))

def unavailable_feedback(message):
    return {'correctness':'insufficient_evidence','feedback':message,'confidence':0,'marks':None,'scoring':[],
            'correct_points':[],'incorrect_points':[],'missing_points':[],'misconceptions':[],'follow_up':'','follow_up_citations':[]}

_evaluating=set()
async def evaluate_saved_response(response_id):
    if response_id in _evaluating:return
    _evaluating.add(response_id)
    try:await _evaluate_saved_response(response_id)
    finally:_evaluating.discard(response_id)

async def _evaluate_saved_response(response_id):
    """Grade an already durable answer. No AI output may change the question sequence."""
    with SessionLocal() as db:
        r=db.get(OralResponse,response_id)
        if not r or r.provider!='PENDING REVIEW':return
        s=db.get(OralSession,r.session_id);ex=db.get(VivaExam,s.viva_id);q=db.get(VivaQuestion,r.question_id)
        if s.status=='FINALIZED':return
        question={**q.content,'question_text':q.prompt,'current_prompt':q.prompt,'question_id':q.id,'marks':q.marks,'allow_follow_up':False}
        transcript=r.transcript;rubric=ex.config['rubric'];sources=q.content.get('sources',[]);timed_out=bool(r.evaluation.get('timed_out'))
    try:
        evaluation,provider=await asyncio.wait_for(grounded.evaluate(question,transcript,[],rubric,sources),timeout=20)
        proposed=evaluation.get('marks')
        if proposed is not None and not 0<=proposed<=question['marks']:raise ValueError('Invalid marks')
        evaluation={**evaluation,'follow_up':'','follow_up_citations':[]}
    except Exception as exc:
        log.warning('Formal viva evaluation failed: %s',type(exc).__name__)
        evaluation=unavailable_feedback('AI evaluation unavailable. Answer saved; teacher review required.');provider='PROVIDER FALLBACK';proposed=None
    evaluation['timed_out']=timed_out
    with SessionLocal() as db:
        # Lock the parent, so a finalized teacher review cannot be overwritten.
        r=db.get(OralResponse,response_id)
        if not r:return
        s=locked_session(db,r.session_id)
        if s.status=='FINALIZED':return
        db.execute(update(OralResponse).where(OralResponse.id==response_id,OralResponse.provider=='PENDING REVIEW').values(evaluation=evaluation,provider=provider,proposed_marks=proposed));db.commit()

def schedule_evaluations(db,s,tasks):
    if tasks is None or s.status=='FINALIZED':return
    for rid in db.scalars(select(OralResponse.id).where(OralResponse.session_id==s.id,OralResponse.provider=='PENDING REVIEW')):
        # Idempotent conditional result write protects concurrent recovery requests.
        tasks.add_task(evaluate_saved_response,rid)

def save_turn(db,s,ex,text,at,timed_out=False):
    """Store one approved question response and advance atomically, before grading."""
    q=db.get(VivaQuestion,s.question_ids[s.cursor]);turn=s.turn
    text=text.strip();cursor=s.cursor+1;complete=cursor>=len(s.question_ids)
    if text:
        evaluation=unavailable_feedback('Answer saved. AI evaluation pending.');provider='PENDING REVIEW';marks=None
    else:
        evaluation=unavailable_feedback('No answer submitted before time expired.' if timed_out else 'No answer submitted.')
        evaluation.update(correctness='incorrect',marks=0,missing_points=['No answer submitted.']);provider='UNANSWERED';marks=0
    evaluation['timed_out']=timed_out
    following=clock_state(min(s.expires,at+timedelta(seconds=QUESTION_SECONDS))) if not complete else None
    claim=db.execute(update(OralSession).where(OralSession.id==s.id,OralSession.turn==turn,OralSession.status=='IN_PROGRESS').values(turn=turn+1,cursor=cursor,follow_depth=0,next_prompt=following,status='TEACHER_REVIEW_REQUIRED' if complete else 'IN_PROGRESS',submitted=at if complete else None))
    if claim.rowcount!=1:db.rollback();raise HTTPException(409,'Answer already saved. Refresh the session.')
    db.add(OralResponse(session_id=s.id,question_id=q.id,turn=turn,depth=0,prompt=q.prompt,transcript=text,evaluation=evaluation,proposed_marks=marks,provider=provider))
    db.flush();db.refresh(s)
    if complete:notify_formal_review(db,s,ex)

def finish_expired(db,s,tasks=None):
    if s.status!='IN_PROGRESS':
        schedule_evaluations(db,s,tasks);return
    # Old in-progress sessions retain their question IDs and answers. A pending
    # follow-up is discarded, and already answered main questions are not reissued.
    s=locked_session(db,s.id)
    if s.status!='IN_PROGRESS':
        db.commit();schedule_evaluations(db,s,tasks);return
    ex=db.get(VivaExam,s.viva_id);stamp=now();changed=False
    if not (s.next_prompt or {}).get('fixed_viva'):
        if s.follow_depth:
            s.cursor+=1
        s.follow_depth=0
        if s.cursor>=len(s.question_ids):
            s.status='TEACHER_REVIEW_REQUIRED';s.submitted=stamp;s.next_prompt=None;notify_formal_review(db,s,ex)
        else:s.next_prompt=clock_state(min(s.expires,stamp+timedelta(seconds=QUESTION_SECONDS)))
        db.flush();changed=True
    while s.status=='IN_PROGRESS' and datetime.fromisoformat(s.next_prompt['deadline'])<=stamp:
        deadline=datetime.fromisoformat(s.next_prompt['deadline'])
        save_turn(db,s,ex,s.next_prompt.get('draft',''),deadline,True);changed=True
    if changed:db.commit()
    # If no changes occurred, release the lock before any asynchronous work.
    else:db.commit()
    schedule_evaluations(db,s,tasks)

def collect_due_vivas():
    """Recover expired turns and durable ungraded answers, even with no browser open."""
    stamp=now()
    with SessionLocal() as db:
        ids=list(db.scalars(select(OralSession.id).where(OralSession.status=='IN_PROGRESS',or_(OralSession.expires<=stamp,OralSession.next_prompt['deadline'].as_string()<=stamp.isoformat())).order_by(OralSession.expires).limit(100)))
        for sid in ids:
            s=db.get(OralSession,sid)
            if s:finish_expired(db,s)
        pending=list(db.scalars(select(OralResponse.id).join(OralSession,OralSession.id==OralResponse.session_id).where(OralResponse.provider=='PENDING REVIEW',OralSession.status!='FINALIZED').order_by(OralResponse.id).limit(20)))
        active=db.scalar(select(OralSession.id).where(OralSession.status=='IN_PROGRESS').limit(1)) is not None
    return pending,active

async def viva_deadline_worker():
    """Bounded recovery loop; stored deadlines survive browser closure and app restarts."""
    from starlette.concurrency import run_in_threadpool
    jobs=set()
    try:
        while True:
            try:
                pending,active=await run_in_threadpool(collect_due_vivas)
                jobs={job for job in jobs if not job.done()}
                for rid in pending:
                    if len(jobs)>=2:break
                    if rid not in _evaluating:
                        jobs.add(asyncio.create_task(evaluate_saved_response(rid)))
                await asyncio.sleep(5 if active or pending else 25)
            except asyncio.CancelledError:raise
            except Exception as exc:
                log.warning('Viva deadline recovery failed: %s',type(exc).__name__)
                await asyncio.sleep(10)
    finally:
        for job in jobs:job.cancel()
        if jobs:await asyncio.gather(*jobs,return_exceptions=True)


def session_payload(db,s,ex,teacher=False,tasks=None):
    finish_expired(db,s,tasks);records,latest=latest_responses(db,s);questions=[db.get(VivaQuestion,qid) for qid in s.question_ids]
    reviews={r.question_id:r for r in db.scalars(select(OralReview).where(OralReview.session_id==s.id))}
    complete=s.status!='IN_PROGRESS';feedback=teacher
    proposed=[latest[q.id].proposed_marks if q.id in latest else (0 if complete else None) for q in questions]
    total_ai=round(sum(proposed),2) if complete and all(v is not None for v in proposed) else None
    confirmed=round(sum(r.marks for r in reviews.values()),2) if s.status=='FINALIZED' else None
    result={'id':s.id,'viva_id':ex.id,'title':ex.title,'course_id':ex.course_id,'status':s.status,'index':s.cursor,'turn':s.turn,'total':len(questions),'total_marks':ex.config['total_marks'],'expires':s.expires,'created':s.created,'complete':complete,'follow_up_depth':0,'immediate_feedback':False,'ai_proposed_marks':total_ai if teacher else None,'confirmed_marks':confirmed if teacher else None,'percentage':round(100*confirmed/ex.config['total_marks'],1) if teacher and confirmed is not None else None,'review_required':True}
    result['responses']=[{'id':r.id,'question_id':r.question_id,'prompt':r.prompt,'transcript':r.transcript,'depth':r.depth,'created':r.created,**({'evaluation':{k:v for k,v in r.evaluation.items() if k not in ('follow_up','follow_up_citations')},'proposed_marks':r.proposed_marks,'provider':r.provider} if feedback else {})} for r in records]
    result['reviews']=[{'question_id':r.question_id,'marks':r.marks,'feedback':r.feedback,'flagged':r.flagged,'finalized':r.finalized} for r in reviews.values()] if teacher else []
    if not complete:
        q=questions[s.cursor];clock=s.next_prompt or {}
        deadline=datetime.fromisoformat(clock['deadline'])
        result.update(question_deadline=deadline,remaining_seconds=max(0,(deadline-now()).total_seconds()),draft=clock.get('draft','') if not teacher else '',draft_revision=clock.get('revision',0) if not teacher else 0)
        result['question']={'id':q.id,'question_text':q.prompt,'marks':q.marks,'type':q.content['question_type'],'topic':db.get(Topic,q.topic_id).name if q.topic_id and ex.config['show_topic'] else None,'is_follow_up':False,'options':q.content.get('options',[])}
    if teacher:
        u=db.get(User,s.student_id);result.update(student_id=u.id,name=u.name,university_id=u.university_id,questions=[teacher_question(q) for q in questions],rubric=ex.config['rubric'],scope=ex.scope)
    # Release the read transaction before provider background tasks run.
    db.commit()
    return result

@router.get('/courses/{cid}/vivas')
def list_vivas(cid:int,user=Depends(current_user),db=Depends(get_db)):
    course_access(db,user,cid);teacher=user.role=='teacher'
    exams=db.scalars(select(VivaExam).where(VivaExam.course_id==cid).order_by(VivaExam.id.desc())).all()
    return [exam_payload(db,e,teacher) for e in exams if teacher or e.status=='PUBLISHED' and (not e.config.get('student_ids') or user.id in e.config['student_ids'])]
@router.post('/courses/{cid}/vivas',status_code=201)
def create(cid:int,data:CreateViva,user=Depends(current_user),db=Depends(get_db)):
    course_access(db,user,cid,True);resolve(db,cid,data.scope)
    enrolled=set(db.scalars(select(Enrollment.student_id).where(Enrollment.course_id==cid)))
    if not set(data.config.student_ids)<=enrolled:raise HTTPException(422,'Assigned students must be enrolled in this section.')
    ex=VivaExam(course_id=cid,teacher_id=user.id,title=data.title,config={**data.config.model_dump(mode='json'),'review_required':True,'immediate_feedback':False},scope=data.scope.model_dump(),status='DRAFT');db.add(ex);audit(db,user,'viva created',cid);db.commit();return exam_payload(db,ex,True)
@router.get('/vivas/{eid}')
def get_exam(eid:int,user=Depends(current_user),db=Depends(get_db)):
    ex=exam_access(db,user,eid);return exam_payload(db,ex,user.role=='teacher')

def mutable(ex):
    if ex.status!='DRAFT':raise HTTPException(409,'Published viva is immutable. Create a new draft for changes.')

def lock_draft(db,ex):
    changed=db.execute(update(VivaExam).where(VivaExam.id==ex.id,VivaExam.status=='DRAFT').values(status='DRAFT'))
    if changed.rowcount!=1:db.rollback();raise HTTPException(409,'Viva has already been published.')

def store_question(db,ex,data,approved=False,sources=None,provider='MANUAL'):
    values=data.model_dump();q=VivaQuestion(viva_id=ex.id,topic_id=data.topic_id,prompt=data.question_text,marks=data.marks,approved=approved,content={**values,'sources':sources or [],'provider':provider});db.add(q);return q

def validate_topic(db,ex,q):
    if q.topic_id:
        topic=db.get(Topic,q.topic_id)
        if not topic or topic.course_id!=ex.course_id:raise HTTPException(422,'Question topic is outside the course.')
        if ex.scope.get('topic_ids') and q.topic_id not in ex.scope['topic_ids']:raise HTTPException(422,'Question topic is outside the selected scope.')
        if ex.scope.get('clos') and topic.clo not in ex.scope['clos']:raise HTTPException(422,'Question CLO is outside scope.')

@router.post('/vivas/{eid}/generate')
async def generate(eid:int,user=Depends(current_user),db=Depends(get_db)):
    ex=exam_access(db,user,eid,True);mutable(ex);throttle(db,'formal-generation:'+str(user.id),15)
    if db.scalar(select(VivaQuestion.id).where(VivaQuestion.viva_id==eid)):raise HTTPException(409,'Delete draft questions before regenerating the full set, or add a manual question.')
    context=evidence_for(db,ex);topics=[{'id':t.id,'name':t.name,'clo':t.clo,'source_ids':(t.structure or {}).get('source_ids',[])} for t in db.scalars(select(Topic).where(Topic.course_id==ex.course_id)) if visible_topic(t)]
    try:
        qs,provider=await grounded.questions(context,topics,ex.config)
        for q in qs:
            validate_topic(db,ex,q)
            if q.question_type not in ex.config['question_types']:raise ValueError('Question type does not match the requested configuration.')
        if ex.config['difficulty']!='Mixed' and any(q.difficulty!=int(ex.config['difficulty']) for q in qs):raise ValueError('Generated difficulty does not match the configuration.')
        if ex.config['bloom_distribution']:
            from app.assessment.selection import quotas
            expected=quotas(ex.config['bloom_distribution'],len(qs),{})
            actual=Counter(q.bloom for q in qs)
            if any(actual.get(k,0)!=v for k,v in expected.items()) or set(actual)-set(expected):raise ValueError('Generated Bloom distribution does not match the configuration.')
        lock_draft(db,ex)
        if db.scalar(select(VivaQuestion.id).where(VivaQuestion.viva_id==eid)):raise HTTPException(409,'Another request added questions. Refresh the draft.')
        for q in qs:store_question(db,ex,q,approved=not ex.config['question_review_required'],sources=validate_citations(q.citations,context),provider=provider)
    except HTTPException:raise
    except Exception as exc:db.rollback();raise HTTPException(502,str(exc) if isinstance(exc,ValueError) else 'Question generation unavailable. Add supported questions manually or try again.')
    audit(db,user,'viva questions generated',eid);db.commit();return exam_payload(db,ex,True)
class GenerateMore(Input):
    count:int=Field(default=10,ge=1,le=30)

@router.post('/vivas/{eid}/generate-more')
async def generate_more(eid:int,data:GenerateMore,user=Depends(current_user),db=Depends(get_db)):
    """Extend a draft question bank, retaining teacher approval and source checks."""
    ex=exam_access(db,user,eid,True);mutable(ex)
    raise HTTPException(409,'Assigned viva uses a fixed approved set. Add or edit only the questions needed for the configured count.')

@router.post('/vivas/{eid}/questions',status_code=201)
async def add_question(eid:int,data:AddQuestion,user=Depends(current_user),db=Depends(get_db)):
    ex=exam_access(db,user,eid,True);mutable(ex);lock_draft(db,ex);validate_topic(db,ex,data)
    try:sources=validate_citations(data.citations,evidence_for(db,ex))
    except ValueError as exc:raise HTTPException(422,str(exc))
    store_question(db,ex,grounded.GroundedQuestion.model_validate(data.model_dump(exclude={'approved'})),data.approved,sources);db.commit();return exam_payload(db,ex,True)
@router.put('/vivas/{eid}/questions/{qid}')
def edit_question(eid:int,qid:int,data:AddQuestion,user=Depends(current_user),db=Depends(get_db)):
    ex=exam_access(db,user,eid,True);mutable(ex);lock_draft(db,ex);q=db.get(VivaQuestion,qid)
    if not q or q.viva_id!=eid:raise HTTPException(404,'Question not found.')
    validate_topic(db,ex,data)
    try:sources=validate_citations(data.citations,evidence_for(db,ex))
    except ValueError as exc:raise HTTPException(422,str(exc))
    q.prompt=data.question_text;q.topic_id=data.topic_id;q.marks=data.marks;q.approved=data.approved;q.content={**data.model_dump(exclude={'approved'}),'sources':sources,'provider':'TEACHER EDITED'};db.commit();return exam_payload(db,ex,True)
@router.delete('/vivas/{eid}/questions/{qid}')
def delete_question(eid:int,qid:int,user=Depends(current_user),db=Depends(get_db)):
    ex=exam_access(db,user,eid,True);mutable(ex);lock_draft(db,ex);q=db.get(VivaQuestion,qid)
    if not q or q.viva_id!=eid:raise HTTPException(404,'Question not found.')
    db.delete(q);db.commit();return {'ok':True}
@router.post('/vivas/{eid}/questions/{qid}/review')
def question_review(eid:int,qid:int,data:PublishQuestion,user=Depends(current_user),db=Depends(get_db)):
    ex=exam_access(db,user,eid,True);mutable(ex);lock_draft(db,ex);q=db.get(VivaQuestion,qid)
    if not q or q.viva_id!=eid:raise HTTPException(404,'Question not found.')
    q.approved=data.approved;db.commit();return {'ok':True}
@router.post('/vivas/{eid}/publish')
def publish(eid:int,user=Depends(current_user),db=Depends(get_db)):
    ex=exam_access(db,user,eid,True);mutable(ex);lock_draft(db,ex);qs=db.scalars(select(VivaQuestion).where(VivaQuestion.viva_id==eid,VivaQuestion.approved.is_(True))).all()
    count=ex.config['count']
    if len(qs)!=count or abs(sum(q.marks for q in qs)-ex.config['total_marks'])>.001:
        raise HTTPException(409,'Approve exactly the configured question count, with marks adding to the configured total.')
    ex.config={**ex.config,'personalize_questions':False,'follow_up_depth':0,'minutes':count*2,'review_required':True,'immediate_feedback':False}
    context=evidence_for(db,ex)
    for q in qs:
        try:validate_citations(q.content['citations'],context)
        except ValueError as exc:raise HTTPException(422,str(exc))
    ex.status='PUBLISHED'
    from app.services.notifications import notify_published_viva
    notify_published_viva(db,ex)
    audit(db,user,'viva published',eid);db.commit();return exam_payload(db,ex,True)
@router.post('/vivas/{eid}/start')
def start(eid:int,tasks:BackgroundTasks,user=Depends(current_user),db=Depends(get_db)):
    role(user,'student');ex=exam_access(db,user,eid)
    # Serialize concurrent start requests for the same exam (PostgreSQL).
    db.scalar(select(VivaExam.id).where(VivaExam.id==eid).with_for_update())
    old=db.scalar(select(OralSession).where(OralSession.viva_id==eid,OralSession.student_id==user.id))
    if old:return session_payload(db,old,ex,tasks=tasks)
    stamp=now()
    for key in ('starts','ends'):
        value=ex.config.get(key)
        if value:
            date=utc_naive(datetime.fromisoformat(value))
            if (key=='starts' and stamp<date) or (key=='ends' and stamp>=date):raise HTTPException(409,'Viva is outside its availability window.')
    ids=list(db.scalars(select(VivaQuestion.id).where(VivaQuestion.viva_id==eid,VivaQuestion.approved.is_(True)).order_by(VivaQuestion.id)))
    if len(ids)!=ex.config['count']:raise HTTPException(409,'This older viva has a mismatched approved pool. Ask your teacher to publish a new fixed-count viva.')
    expiry=stamp+timedelta(seconds=QUESTION_SECONDS*len(ids))
    if ex.config.get('ends'):expiry=min(expiry,utc_naive(datetime.fromisoformat(ex.config['ends'])))
    s=OralSession(viva_id=eid,student_id=user.id,question_ids=ids,cursor=0,turn=0,follow_depth=0,status='IN_PROGRESS',expires=expiry,next_prompt=clock_state(min(expiry,stamp+timedelta(seconds=QUESTION_SECONDS))))
    db.add(s);db.commit();return session_payload(db,s,ex,tasks=tasks)

@router.get('/oral-sessions/{sid}')
def get_session(sid:int,tasks:BackgroundTasks,user=Depends(current_user),db=Depends(get_db)):
    s,ex=session_access(db,user,sid);return session_payload(db,s,ex,tasks=tasks)

@router.put('/oral-sessions/{sid}/draft')
def save_draft(sid:int,data:OralDraft,tasks:BackgroundTasks,user=Depends(current_user),db=Depends(get_db)):
    role(user,'student');s,ex=session_access(db,user,sid)
    if s.status=='IN_PROGRESS' and not (s.next_prompt or {}).get('fixed_viva'):finish_expired(db,s,tasks)
    s=locked_session(db,sid)
    if s.status!='IN_PROGRESS' or s.turn!=data.turn or datetime.fromisoformat(s.next_prompt['deadline'])<=now():raise HTTPException(409,'Question time is over or answer already saved.')
    if data.revision>(s.next_prompt or {}).get('revision',0):
        updated={**s.next_prompt,'draft':data.transcript,'revision':data.revision}
        claim=db.execute(update(OralSession).where(OralSession.id==sid,OralSession.turn==data.turn,OralSession.status=='IN_PROGRESS').values(next_prompt=updated))
        if claim.rowcount!=1:db.rollback();raise HTTPException(409,'Question changed.')
    db.commit();return {'saved':True}

@router.post('/oral-sessions/{sid}/answer')
def answer(sid:int,data:OralAnswer,tasks:BackgroundTasks,user=Depends(current_user),db=Depends(get_db)):
    role(user,'student');s,ex=session_access(db,user,sid)
    # Do not run an evaluator before the answer is durably stored.
    if not (s.next_prompt or {}).get('fixed_viva') and s.status=='IN_PROGRESS':finish_expired(db,s)
    s=locked_session(db,sid)
    if s.status!='IN_PROGRESS' or s.turn!=data.turn:raise HTTPException(409,'This turn is already saved or is not currently issued.')
    stamp=now();deadline=datetime.fromisoformat(s.next_prompt['deadline']);late=stamp>=deadline
    # At/after the deadline only the last server-acknowledged draft is accepted.
    text=s.next_prompt.get('draft','') if late else data.transcript
    save_turn(db,s,ex,text,deadline if late else stamp,late);db.commit()
    return session_payload(db,s,ex,tasks=tasks)

@router.post('/oral-sessions/{sid}/finish')
def finish(sid:int,tasks:BackgroundTasks,user=Depends(current_user),db=Depends(get_db)):
    role(user,'student');s,ex=session_access(db,user,sid);finish_expired(db,s)
    s=locked_session(db,sid)
    if s.status=='IN_PROGRESS':
        # Early submission records the current saved draft and remaining blanks.
        stamp=now();save_turn(db,s,ex,s.next_prompt.get('draft',''),stamp)
        while s.status=='IN_PROGRESS':save_turn(db,s,ex,'',stamp)
        db.commit()
    return session_payload(db,s,ex,tasks=tasks)

@router.get('/courses/{cid}/oral-history')
def history(cid:int,tasks:BackgroundTasks,user=Depends(current_user),db=Depends(get_db)):
    role(user,'student');course_access(db,user,cid)
    rows=db.scalars(select(OralSession).join(VivaExam,VivaExam.id==OralSession.viva_id).where(VivaExam.course_id==cid,OralSession.student_id==user.id).order_by(OralSession.id.desc()).limit(100)).all()
    return [session_payload(db,s,db.get(VivaExam,s.viva_id),tasks=tasks) for s in rows]
@router.get('/courses/{cid}/oral-review')
def queue(cid:int,tasks:BackgroundTasks,q:str='',user=Depends(current_user),db=Depends(get_db)):
    course_access(db,user,cid,True)
    rows=db.scalars(select(OralSession).join(VivaExam,VivaExam.id==OralSession.viva_id).join(User,User.id==OralSession.student_id).where(VivaExam.course_id==cid).order_by(OralSession.created.desc()).limit(300)).all()
    return [session_payload(db,s,db.get(VivaExam,s.viva_id),True,tasks=tasks) for s in rows if q.lower() in (db.get(User,s.student_id).name+' '+db.get(User,s.student_id).university_id).lower()]
@router.put('/oral-sessions/{sid}/questions/{qid}/review')
def review(sid:int,qid:int,data:ReviewMarks,user=Depends(current_user),db=Depends(get_db)):
    s,ex=session_access(db,user,sid,True);finish_expired(db,s)
    if s.status in ('IN_PROGRESS','FINALIZED'):raise HTTPException(409,'Submit the session before review; finalized results cannot be overwritten.')
    claim=db.execute(update(OralSession).where(OralSession.id==sid,OralSession.status=='TEACHER_REVIEW_REQUIRED').values(status='TEACHER_REVIEW_REQUIRED'))
    if claim.rowcount!=1:db.rollback();raise HTTPException(409,'Session changed. Refresh before reviewing.')
    if qid not in s.question_ids:raise HTTPException(404,'Question not in this session.')
    question=db.get(VivaQuestion,qid)
    if data.marks>question.marks:raise HTTPException(422,'Marks exceed this question maximum.')
    r=db.scalar(select(OralReview).where(OralReview.session_id==sid,OralReview.question_id==qid))
    if not r:r=OralReview(session_id=sid,question_id=qid,teacher_id=user.id);db.add(r)
    r.marks=data.marks;r.feedback=data.feedback;r.flagged=data.flagged;r.teacher_id=user.id
    audit(db,user,'viva marks reviewed',f'{sid}:{qid}');db.commit();return session_payload(db,s,ex,True)

def finalize(db,s,ex,user,automated=False):
    claimed=db.execute(update(OralSession).where(OralSession.id==s.id,OralSession.status=='TEACHER_REVIEW_REQUIRED').values(status='FINALIZED'))
    if claimed.rowcount!=1:db.rollback();raise HTTPException(409,'This viva has already been finalized or is still active.')
    reviews=list(db.scalars(select(OralReview).where(OralReview.session_id==s.id)))
    if {r.question_id for r in reviews}!=set(s.question_ids):db.rollback();raise HTTPException(409,'Review every main question before finalizing.')
    if any(r.flagged for r in reviews):db.rollback();raise HTTPException(409,'Resolve flagged evaluations before finalizing.')
    for r in reviews:
        r.finalized=True;q=db.get(VivaQuestion,r.question_id)
        if q.topic_id and not automated:
            m=db.scalar(select(Mastery).where(Mastery.student_id==s.student_id,Mastery.topic_id==q.topic_id))
            if not m:m=Mastery(student_id=s.student_id,topic_id=q.topic_id,probability=.2,attempts=0,correct=0);db.add(m);db.flush()
            before=m.probability;correct=r.marks/q.marks>=.7;after=before+.35*(update_mastery(before,correct,q.content['difficulty'],guess=.1)-before)
            changed=db.execute(update(Mastery).where(Mastery.id==m.id,Mastery.attempts==m.attempts,Mastery.probability==before).values(probability=after,attempts=Mastery.attempts+1,correct=Mastery.correct+int(correct),last_practiced=now()))
            if changed.rowcount!=1:db.rollback();raise HTTPException(409,'Learning evidence changed concurrently. Retry finalization.')
            db.refresh(m);r.mastery_before=before;r.mastery_after=after
            for due in revision_dates(now(),after):db.add(Revision(student_id=s.student_id,topic_id=q.topic_id,due=due))
    total=round(sum(r.marks for r in reviews),2)
    notify(db,s.student_id,ex.course_id,f'oral-final:{s.id}',ex.title+' graded',f'{ex.title} has been reviewed. Contact your teacher for feedback.','formal-viva')
    audit(db,user,'viva auto-finalized' if automated else 'viva finalized',s.id);db.commit();db.refresh(s)

def auto_finalize(db,s,ex):
    _,latest=latest_responses(db,s)
    if any(qid not in latest or latest[qid].proposed_marks is None or latest[qid].evaluation.get('confidence',0)<.7 for qid in s.question_ids):return
    for qid in s.question_ids:
        r=latest[qid];db.add(OralReview(session_id=s.id,question_id=qid,teacher_id=ex.teacher_id,marks=r.proposed_marks,feedback='AUTO-FINALIZED: '+r.evaluation['feedback'],flagged=False))
    db.flush();finalize(db,s,ex,db.get(User,ex.teacher_id),automated=True)
@router.post('/oral-sessions/{sid}/finalize')
def confirm(sid:int,user=Depends(current_user),db=Depends(get_db)):
    s,ex=session_access(db,user,sid,True);finalize(db,s,ex,user);return session_payload(db,s,ex,True)
@router.get('/courses/{cid}/viva-analytics')
def analytics(cid:int,user=Depends(current_user),db=Depends(get_db)):
    course_access(db,user,cid,True)
    sessions=db.scalars(select(OralSession).join(VivaExam,VivaExam.id==OralSession.viva_id).where(VivaExam.course_id==cid)).all()
    scores=[];groups={'topics':defaultdict(list),'clos':defaultdict(list),'difficulty':defaultdict(list)};missing=Counter();mistakes=Counter();support=[]
    for s in sessions:
        records,latest=latest_responses(db,s)
        for r in latest.values():missing.update(r.evaluation.get('missing_points',[]));mistakes.update(r.evaluation.get('misconceptions',[]))
        if s.status!='FINALIZED':continue
        reviews=db.scalars(select(OralReview).where(OralReview.session_id==s.id)).all();ex=db.get(VivaExam,s.viva_id)
        pct=100*sum(r.marks for r in reviews)/ex.config['total_marks'];scores.append(pct)
        if pct<60:
            u=db.get(User,s.student_id);support.append({'name':u.name,'university_id':u.university_id,'percentage':round(pct,1),'viva':ex.title})
        for r in reviews:
            question=db.get(VivaQuestion,r.question_id);pct=100*r.marks/question.marks
            groups['topics'][db.get(Topic,question.topic_id).name if question.topic_id else 'Unmapped'].append(pct);groups['clos'][question.content.get('clo') or 'Unmapped'].append(pct);groups['difficulty'][str(question.content['difficulty'])].append(pct)
    return {'sessions':len(sessions),'finalized':len(scores),'class_average':round(sum(scores)/len(scores),1) if scores else None,'highest':round(max(scores),1) if scores else None,**{k:{key:round(sum(vals)/len(vals),1) for key,vals in mapping.items()} for k,mapping in groups.items()},'missing_concepts':missing.most_common(15),'misconceptions':mistakes.most_common(15),'support':support,'methodology':'Marks use finalized sessions. Missing-concept and misconception labels are provisional AI observations requiring teacher interpretation.'}

@router.post('/vivas/{eid}/questions/{qid}/regenerate')
async def regenerate(eid:int,qid:int,user=Depends(current_user),db=Depends(get_db)):
    ex=exam_access(db,user,eid,True);mutable(ex);q=db.get(VivaQuestion,qid)
    if not q or q.viva_id!=eid:raise HTTPException(404,'Question not found.')
    throttle(db,'formal-generation:'+str(user.id),15)
    evidence=evidence_for(db,ex)
    config={**ex.config,'count':1,'total_marks':q.marks,'bloom_distribution':{},'question_types':[q.content['question_type']]}
    topics=[{'id':t.id,'name':t.name,'clo':t.clo,'source_ids':(t.structure or {}).get('source_ids',[])} for t in db.scalars(select(Topic).where(Topic.course_id==ex.course_id)) if visible_topic(t)]
    try:
        generated,provider=await grounded.questions(evidence,topics,config);draft=generated[0];validate_topic(db,ex,draft);sources=validate_citations(draft.citations,evidence)
        if draft.question_type not in config['question_types'] or (config['difficulty']!='Mixed' and draft.difficulty!=int(config['difficulty'])):
            raise ValueError('Regenerated question does not match the requested type or difficulty.')
    except Exception:raise HTTPException(502,'Regeneration failed validation; the previous draft was preserved.')
    # Recheck publication after the provider call before changing the draft.
    claim=db.execute(update(VivaExam).where(VivaExam.id==eid,VivaExam.status=='DRAFT').values(status='DRAFT'))
    if claim.rowcount!=1:db.rollback();raise HTTPException(409,'Viva was published during generation.')
    q.prompt=draft.question_text;q.topic_id=draft.topic_id;q.content={**draft.model_dump(),'sources':sources,'provider':provider};q.approved=False
    db.commit();return exam_payload(db,ex,True)
