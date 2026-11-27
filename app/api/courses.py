import secrets
from pathlib import Path
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from sqlalchemy import select, or_
from sqlalchemy.exc import IntegrityError
from app.db import get_db
from app.models import Course,Enrollment,Topic,Resource,ResourceBlob,Chunk,Question
from app.schemas import CourseInput,CodeInput,TopicInput,QuestionInput
from app.auth.security import current_user,role,course_access,audit,teacher_courses
from app.documents.extract import extract
from app.knowledge_graph.engine import validate_dag
from app.config import MAX_UPLOAD,BACKGROUND_UPLOAD_BYTES
router=APIRouter(prefix='/api')
def course_dict(c,user):
    result={k:getattr(c,k) for k in ('id','name','code','section','semester','description','clos','material_only')}
    if user.role=='teacher':result['enrollment_code']=c.enrollment_code
    return result
@router.get('/courses')
def courses(user=Depends(current_user),db=Depends(get_db)):
    if user.role=='teacher':q=select(Course).where(Course.id.in_(teacher_courses(user)))
    elif user.role=='student':q=select(Course).join(Enrollment,Enrollment.course_id==Course.id).where(Enrollment.student_id==user.id)
    else:return []
    return [course_dict(c,user) for c in db.scalars(q)]
@router.post('/courses',status_code=201)
def create(data:CourseInput,user=Depends(current_user),db=Depends(get_db)):
    role(user,'teacher')
    c=Course(**data.model_dump(),teacher_id=user.id,enrollment_code=secrets.token_urlsafe(9));db.add(c);db.flush();audit(db,user,'course created',c.id);db.commit()
    return course_dict(c,user)
@router.post('/courses/join')
def join(data:CodeInput,user=Depends(current_user),db=Depends(get_db)):
    role(user,'student')
    c=db.scalar(select(Course).where(Course.enrollment_code==data.code))
    if not c:raise HTTPException(404,'Invalid enrollment code.')
    db.add(Enrollment(course_id=c.id,student_id=user.id))
    try:
        db.flush()
        from app.services.notifications import refresh_course_updates
        refresh_course_updates(db,user,[c.id])
        db.commit()
    except IntegrityError:db.rollback();raise HTTPException(409,'Already enrolled.')
    return course_dict(c,user)
@router.get('/courses/{cid}/topics')
def topics(cid:int,user=Depends(current_user),db=Depends(get_db)):
    course_access(db,user,cid)
    return [{k:getattr(t,k) for k in ('id','name','description','prerequisites','clo','difficulty')} for t in db.scalars(select(Topic).where(Topic.course_id==cid))]
@router.post('/courses/{cid}/topics',status_code=201)
def add_topic(cid:int,data:TopicInput,user=Depends(current_user),db=Depends(get_db)):
    course_access(db,user,cid,True)
    t=Topic(course_id=cid,**data.model_dump());db.add(t);db.flush()
    try:validate_dag(db.scalars(select(Topic).where(Topic.course_id==cid)).all())
    except ValueError as e:db.rollback();raise HTTPException(422,str(e))
    audit(db,user,'topic created',t.id);db.commit();return {'id':t.id}
@router.put('/courses/{cid}/topics/{tid}')
def edit_topic(cid:int,tid:int,data:TopicInput,user=Depends(current_user),db=Depends(get_db)):
    course_access(db,user,cid,True)
    t=db.get(Topic,tid)
    if not t or t.course_id!=cid:raise HTTPException(404,'Topic not found.')
    for k,v in data.model_dump().items():setattr(t,k,v)
    try:validate_dag(db.scalars(select(Topic).where(Topic.course_id==cid)).all())
    except ValueError as e:db.rollback();raise HTTPException(422,str(e))
    audit(db,user,'topic edited',t.id);db.commit();return {'ok':True}
@router.get('/courses/{cid}/resources')
def resources(cid:int,user=Depends(current_user),db=Depends(get_db)):
    course_access(db,user,cid)
    # Check blob existence without fetching large binary files into server memory.
    available=select(ResourceBlob.resource_id).where(ResourceBlob.resource_id==Resource.id).exists()
    rows=db.execute(select(Resource,available).where(Resource.course_id==cid,or_(Resource.owner_id.is_(None),Resource.owner_id==user.id)).order_by(Resource.created.desc(),Resource.id.desc())).all()
    return [{'id':r.id,'filename':r.filename,'kind':r.kind,'created':r.created,'status':r.status or 'ready','status_detail':r.status_detail,'download_available':bool(has_blob)} for r,has_blob in rows]
@router.post('/courses/{cid}/resources',status_code=201)
def upload(cid:int,file:UploadFile=File(...),user=Depends(current_user),db=Depends(get_db)):
    course_access(db,user,cid)
    data=file.file.read(MAX_UPLOAD+1)
    if len(data)>MAX_UPLOAD:raise HTTPException(413,f'File limit is {MAX_UPLOAD//(1024*1024)} MiB.')
    if not data:raise HTTPException(422,'The file is empty.')
    filename=Path((file.filename or 'upload.txt').replace('\\','/')).name[:200]
    from app.services.indexing import index_resource,semantic_index,start_background,failure_detail
    from app.documents.extract import TEXT_EXT,OFFICE_CONVERT,SUPPORTED_EXT
    suffix=Path(filename).suffix.lower()
    if suffix not in SUPPORTED_EXT:raise HTTPException(422,'Unsupported file type. Choose a supported document, image, audio, video or text file.')
    background=suffix in OFFICE_CONVERT or (BACKGROUND_UPLOAD_BYTES and len(data)>BACKGROUND_UPLOAD_BYTES and suffix not in TEXT_EXT)
    r=Resource(course_id=cid,owner_id=user.id if user.role=='student' else None,filename=filename,kind='PERSONAL MATERIAL' if user.role=='student' else 'COURSE MATERIAL',status='processing' if background else 'ready')
    db.add(r);db.flush()
    db.add(ResourceBlob(resource_id=r.id,data=data,content_type='application/octet-stream'))
    if background:
        # Large book: answer now, read it in the background (avoids host request timeouts).
        from app.services.notifications import notify_material
        notify_material(db,r)
        audit(db,user,'resource queued',r.id);db.commit();start_background(r.id)
        return {'id':r.id,'chunks':0,'status':'processing','message':'Upload received. The document is being read in the background; refresh Materials in a minute.','vector_status':'Indexing in the background'}
    try:count=index_resource(db,r,data)
    except Exception as e:
        db.rollback()
        message=failure_detail(e)
        import logging
        logging.getLogger('campuspath.indexing').warning('Upload indexing failed: %s',type(e).__name__)
        raise HTTPException(422,message)
    r.status_detail=f'{count} source excerpts indexed.'
    from app.services.notifications import notify_material
    notify_material(db,r)
    audit(db,user,'resource indexed',r.id);db.commit()
    vector_status=semantic_index(db,r.id)
    return {'id':r.id,'chunks':count,'status':'ready','message':'Text indexed. Source locations retained.','vector_status':vector_status}
@router.post('/courses/{cid}/resources/{rid}/retry',status_code=202)
def retry_resource(cid:int,rid:int,user=Depends(current_user),db=Depends(get_db)):
    course_access(db,user,cid)
    from sqlalchemy import update
    from app.services.indexing import start_background
    r=db.get(Resource,rid)
    if not r or r.course_id!=cid or (r.owner_id is None and user.role!='teacher') or (r.owner_id is not None and r.owner_id!=user.id):raise HTTPException(404,'Resource not found or access denied.')
    if r.status!='failed':raise HTTPException(409,'Only failed uploads can be retried.')
    if not db.scalar(select(ResourceBlob.resource_id).where(ResourceBlob.resource_id==rid)):raise HTTPException(409,'Original file unavailable. Upload the document again.')
    if db.scalar(select(Chunk.id).where(Chunk.resource_id==rid).limit(1)):raise HTTPException(409,'This resource already has source excerpts. Upload a new version to preserve existing citations.')
    claimed=db.execute(update(Resource).where(Resource.id==rid,Resource.status=='failed').values(status='processing',status_detail='Retry queued.'))
    if claimed.rowcount!=1:db.rollback();raise HTTPException(409,'Indexing already queued.')
    audit(db,user,'resource indexing retried',rid);db.commit();start_background(rid)
    return {'id':rid,'status':'processing','message':'Indexing queued. Refresh Materials to check progress.'}

@router.get('/courses/{cid}/resources/{rid}')
def read_resource(cid:int,rid:int,user=Depends(current_user),db=Depends(get_db)):
    course_access(db,user,cid)
    r=db.get(Resource,rid)
    if not r or r.course_id!=cid or r.owner_id not in (None,user.id):raise HTTPException(404,'Resource not found.')
    from app.services.materials import source_metadata
    return {'filename':r.filename,'status':r.status,'status_detail':r.status_detail,'chunks':[{'id':c.id,'location':c.location,'text':c.text,'structure':source_metadata(c.location,c.text,c.structure)} for c in db.scalars(select(Chunk).where(Chunk.resource_id==rid))]}
@router.get('/courses/{cid}/questions')
def questions(cid:int,user=Depends(current_user),db=Depends(get_db)):
    course_access(db,user,cid,True)
    return [{k:getattr(q,k) for k in ('id','topic_id','prompt','options','correct','explanation','misconception','difficulty','bloom','approved','source','source_ids')} for q in db.scalars(select(Question).where(Question.course_id==cid))]
@router.post('/courses/{cid}/questions',status_code=201)
def question_create(cid:int,data:QuestionInput,user=Depends(current_user),db=Depends(get_db)):
    course_access(db,user,cid,True)
    t=db.get(Topic,data.topic_id)
    if not t or t.course_id!=cid:raise HTTPException(422,'Select a topic from this course.')
    if db.scalar(select(Question.id).where(Question.course_id==cid,Question.prompt==data.prompt)):raise HTTPException(409,'Duplicate question.')
    if data.source_ids:
        from app.services.materials import resolve,MaterialScope
        resolve(db,cid,MaterialScope(chunk_ids=data.source_ids))
    q=Question(course_id=cid,**data.model_dump());db.add(q);db.commit();return {'id':q.id}
@router.put('/courses/{cid}/questions/{qid}')
def question_edit(cid:int,qid:int,data:QuestionInput,user=Depends(current_user),db=Depends(get_db)):
    course_access(db,user,cid,True)
    q=db.get(Question,qid);t=db.get(Topic,data.topic_id)
    if not q or q.course_id!=cid or not t or t.course_id!=cid:raise HTTPException(404,'Question/topic not found.')
    # Preserve evidence: question versions with answers cannot be overwritten.
    from app.models import Answer,QuizRun
    if db.scalar(select(Answer.id).where(Answer.question_id==qid)) or any(qid in r.question_ids for r in db.scalars(select(QuizRun).where(QuizRun.course_id==cid))):
        raise HTTPException(409,'Question has been issued. Create a new version instead.')
    if data.source_ids:
        from app.services.materials import resolve,MaterialScope
        resolve(db,cid,MaterialScope(chunk_ids=data.source_ids))
    for k,v in data.model_dump().items():setattr(q,k,v)
    q.approved=False;db.commit();return {'ok':True}
@router.post('/courses/{cid}/questions/{qid}/{action}')
def review(cid:int,qid:int,action:str,user=Depends(current_user),db=Depends(get_db)):
    course_access(db,user,cid,True)
    q=db.get(Question,qid)
    if not q or q.course_id!=cid:raise HTTPException(404,'Question not found.')
    if action not in ('approve','reject'):raise HTTPException(400,'Unknown review action.')
    q.approved=action=='approve';audit(db,user,'question '+action,qid);db.commit();return {'ok':True}
@router.get('/courses/{cid}/search')
def search(cid:int,q:str='',user=Depends(current_user),db=Depends(get_db)):
    course_access(db,user,cid)
    if not 2<=len(q)<=200:raise HTTPException(422,'Search needs 2–200 characters.')
    from app.ai.retrieval import LexicalStore
    return {'topics':[{'id':t.id,'name':t.name} for t in db.scalars(select(Topic).where(Topic.course_id==cid)) if q.lower() in t.name.lower()],'resources':LexicalStore().search(db,user,cid,q)}
