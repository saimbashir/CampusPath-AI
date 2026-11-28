from datetime import timedelta
import os, asyncio
from fastapi import APIRouter,Depends,HTTPException
from sqlalchemy import select,update,delete
from app.db import get_db
from app.models import VivaSession,VivaTurn,Topic,Mastery,Revision,Misconception,User,Course,now
from app.schemas import VivaStart,VivaAnswer,VivaReview
from app.auth.security import current_user,course_access,role,audit,throttle
from app.services.learning import snapshot
from app.mastery.engine import update_mastery,revision_dates
from app.ai.viva import evaluate,offline_evaluation,material_questions,evaluate_material
from app.services.official_progress import visible_topic
from app.ai.viva_variation import prompt_for_turn
from app.config import DEMO_MODE
router=APIRouter(prefix='/api')
def material_entry(session,index=None):
    i=session.cursor if index is None else index
    if i>=len(session.topic_ids):return None
    entry=session.topic_ids[i]
    return entry if isinstance(entry,dict) else None

def prompt_for(db,session):
    entry=material_entry(session)
    if entry:return db.get(Topic,entry['topic_id']),entry['prompt']
    topic=db.get(Topic,session.topic_ids[session.cursor])
    style,prompt=prompt_for_turn(session.id,session.student_id,session.course_id,session.cursor,topic.name)
    return topic,prompt

def payload(db,session):
    turns=db.scalars(select(VivaTurn).where(VivaTurn.session_id==session.id).order_by(VivaTurn.turn_index)).all()
    result={'id':session.id,'index':session.cursor,'total':len(session.topic_ids),'complete':session.cursor>=len(session.topic_ids) or session.expires<now(),
        'turns':[{'id':t.id,'topic_id':t.topic_id,'prompt':t.prompt,'answer':t.answer,'evaluation':t.evaluation,'provider':t.provider,'proposed_score':t.proposed_score,'reviewed_score':t.reviewed_score,'teacher_feedback':t.teacher_feedback,'mastery_before':t.mastery_before,'mastery_after':t.mastery_after} for t in turns]}
    if not result['complete']:
        topic,prompt=prompt_for(db,session);entry=material_entry(session)
        result['question']={'topic_id':topic.id,'topic':entry.get('topic_name',topic.name) if entry else topic.name,'prompt':prompt,'style':entry['style'] if entry else prompt_for_turn(session.id,session.student_id,session.course_id,session.cursor,topic.name)[0]}
        if entry:
            result['question']['source_locations']=[{'filename':s['filename'],'location':s['location']} for s in entry['sources']]
            result['question']['provider']=entry['provider']
            result['question']['language']=entry['language']
    result['material_based']=bool(session.topic_ids and isinstance(session.topic_ids[0],dict))
    result['private_practice']=True
    if result['material_based'] and any(isinstance(item,dict) and item.get('style')=='Revision practice' for item in session.topic_ids):
        result['coverage_notice']='Offline practice includes revision of the selected concepts. For more varied AI-generated questions, use a configured live AI provider or select a wider slide range.'
    elif result['material_based'] and session.topic_ids[0].get('requested_count',result['total'])>result['total']:
        result['coverage_notice']='Only some requested questions passed validation within the generation limit. Choose more source material or start another session for additional practice.'
    return result
@router.post('/courses/{cid}/viva/start')
async def start(cid:int,data:VivaStart,user=Depends(current_user),db=Depends(get_db)):
    role(user,'student');course_access(db,user,cid)
    topics=[t for t in db.scalars(select(Topic).where(Topic.course_id==cid)) if visible_topic(t)]
    from app.models import Resource,Chunk
    ready=db.scalar(select(Chunk.id).join(Resource,Resource.id==Chunk.resource_id).where(Resource.course_id==cid,Resource.owner_id.is_(None),Resource.status=='ready').limit(1))
    use_material=bool(data.material_based or data.resource_ids or data.chapters or data.page_from or data.page_to or data.heading or (not data.topic_id and (ready is not None or not topics)))
    if use_material:
        from app.services.materials import MaterialScope,resolve
        scope=MaterialScope(resource_ids=data.resource_ids,chapters=data.chapters,page_from=data.page_from,page_to=data.page_to,heading=data.heading)
        evidence=resolve(db,cid,scope,limit=None)
        # Throttle generation independently of the existing per-answer limit.
        throttle(db,'material-practice:'+str(user.id),10)
        try:questions=await material_questions(evidence,data.count,data.language,data.difficulty)
        except ValueError as exc:raise HTTPException(422,str(exc))
        # Serialize automatic concept creation for a course; never hold a write
        # lock while the AI provider is running.
        db.execute(select(Course.id).where(Course.id==cid).with_for_update()).scalar_one()
        topics=list(db.scalars(select(Topic).where(Topic.course_id==cid)))
        anchor=next((t for t in topics if (t.structure or {}).get('practice_anchor')),None)
        if anchor is None:
            anchor=Topic(course_id=cid,name='Private practice (internal)',description='',prerequisites=[],clo='Private practice',difficulty=1,structure={'practice_anchor':True,'automatic_material_topic':True});db.add(anchor);db.flush()
        from app.ai.viva_variation import material_concept
        topic_ids=[]
        for question in questions:
            source=question['sources'][0]
            topic_ids.append({**question,'topic_id':anchor.id,'topic_name':material_concept(source) or 'Selected course material','requested_count':data.count})
    else:
        if data.topic_id:
            topics=[t for t in topics if t.id==data.topic_id]
        else:
            order=[x['id'] for x in snapshot(db,user.id,cid)['path']]
            topics.sort(key=lambda t:order.index(t.id) if t.id in order else len(order))
        if not topics:raise HTTPException(409,'No concepts match this selection. Choose teacher material for practice.')
        topic_ids=[topics[i % len(topics)].id for i in range(data.count)]
    session=VivaSession(student_id=user.id,course_id=cid,topic_ids=topic_ids,cursor=0,expires=now()+timedelta(hours=1))
    db.add(session);db.commit();return payload(db,session)
@router.get('/viva/{vid}')
def get_viva(vid:int,user=Depends(current_user),db=Depends(get_db)):
    session=db.get(VivaSession,vid)
    if not session or session.student_id!=user.id:raise HTTPException(404,'Viva not found.')
    course_access(db,user,session.course_id);return payload(db,session)
@router.post('/viva/{vid}/answer')
async def answer_viva(vid:int,data:VivaAnswer,user=Depends(current_user),db=Depends(get_db)):
    role(user,'student');session=db.get(VivaSession,vid)
    if not session or session.student_id!=user.id:raise HTTPException(404,'Viva not found.')
    course_access(db,user,session.course_id);throttle(db,'viva:'+str(user.id),30)
    if session.expires<now() or session.cursor>=len(session.topic_ids):raise HTTPException(409,'Viva is complete or expired.')
    if data.turn_index!=session.cursor:raise HTTPException(409,'This turn is already submitted or not currently issued.')
    topic,prompt=prompt_for(db,session);index=session.cursor
    entry=material_entry(session)
    reference='\n\n'.join(f"{s['filename']} · {s['location']}\n{s['text']}" for s in entry['sources']) if entry else topic.description
    topic_name=entry.get('topic_name',topic.name) if entry else topic.name
    evaluation=offline_evaluation(topic_name,reference,data.text);score=None;provider='PRACTICE OFFLINE' if entry else 'PRACTICE OFFLINE'
    if entry:
        evaluation['feedback']='Compare your response with the exact course excerpts below. No live AI score is available.'
        evaluation['follow_up']=''
    if not DEMO_MODE and os.getenv('LLM_API_KEY'):
        try:
            result=await asyncio.wait_for(evaluate_material(prompt,data.text,topic_name,entry['sources'],entry['language']) if entry else evaluate(prompt,data.text,topic_name,reference),timeout=30)
            evaluation=result.model_dump();score=result.score;provider='AI PRACTICE'
        except Exception:
            provider='PRACTICE FALLBACK'
            evaluation['feedback']='The AI evaluator is unavailable. Compare your answer with the source below; no AI score was invented.' if entry else 'The AI evaluator is unavailable. Your private transcript is saved; no AI score was invented.'
    if entry:
        evaluation['reference']=reference
        evaluation['sources']=[{'id':s['id'],'filename':s['filename'],'location':s['location'],'text':s['text']} for s in entry['sources']]
    claimed=db.execute(update(VivaSession).where(VivaSession.id==vid,VivaSession.cursor==index).values(cursor=index+1))
    if claimed.rowcount!=1:db.rollback();raise HTTPException(409,'This turn was already saved in another request.')
    turn=VivaTurn(session_id=vid,turn_index=index,topic_id=topic.id,prompt=prompt,answer=data.text,evaluation=evaluation,provider=provider,proposed_score=score)
    db.add(turn);db.commit();db.refresh(session)
    return {'evaluation':evaluation,'proposed_score':score,'status':provider,'message':'Personal material practice is formative; it does not affect official marks or require teacher review.' if entry else 'Personal practice is private and does not affect official marks.','next':payload(db,session)}
@router.get('/courses/{cid}/viva/history')
def viva_history(cid:int,user=Depends(current_user),db=Depends(get_db)):
    role(user,'student');course_access(db,user,cid)
    return [payload(db,s) for s in db.scalars(select(VivaSession).where(VivaSession.course_id==cid,VivaSession.student_id==user.id).order_by(VivaSession.id.desc()).limit(15))]
@router.get('/courses/{cid}/viva/review')
def review_queue(cid:int,user=Depends(current_user),db=Depends(get_db)):
    course_access(db,user,cid,True)
    return []
@router.post('/viva/turns/{tid}/review')
def review(tid:int,data:VivaReview,user=Depends(current_user),db=Depends(get_db)):
    role(user,'teacher')
    raise HTTPException(403,'Personal practice is private. Review assigned vivas instead.')
