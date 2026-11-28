import os, asyncio, logging
from datetime import timedelta
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from app.db import get_db
from app.models import Course,Topic,Question,QuizRun,Answer,Revision,Conversation,now
from app.schemas import TutorInput,StartQuiz,AnswerInput,PlanInput,TextInput
from app.auth.security import current_user,role,course_access,student_access
from app.services.learning import snapshot,observe
from app.mastery.engine import next_difficulty
from app.ai.retrieval import LexicalStore,HybridStore
from app.ai.providers import CompatibleLLM
from app.knowledge_graph.engine import algorithm_steps
from app.config import DEMO_MODE
router=APIRouter(prefix='/api')
from app.assessment.feedback import teaching_feedback
@router.get('/courses/{cid}/students/{sid}/progress')
def progress(cid:int,sid:int,user=Depends(current_user),db=Depends(get_db)):
    student_access(db,user,cid,sid)
    if user.role=='teacher':
        from app.services.official_progress import official_snapshot
        result=official_snapshot(db,sid,cid)
    else:
        from app.services.private_progress import private_progress
        result=private_progress(db,sid,cid,snapshot(db,sid,cid))
    db.commit();return result
@router.post('/courses/{cid}/tutor')
async def tutor(cid:int,data:TutorInput,user=Depends(current_user),db=Depends(get_db)):
    course_access(db,user,cid)
    from starlette.concurrency import run_in_threadpool
    from app.services.materials import MaterialScope,resolve
    from app.ai.retrieval import focus_evidence
    from app.models import Resource
    import re
    question=data.question
    chapter=re.search(r'chapter\s+(\d+)',question,re.I)
    position=re.search(r'(?:slides?|pages?)\s+(\d+)(?:\s*(?:[-–—]|to|through)\s*(?:(?:slides?|pages?)\s+)?(\d+))?',question,re.I)
    overview=bool(re.search(r'\b(?:summari[sz]e|summary|overview|all slides|whole presentation|entire (?:presentation|course|lecture))\b',question,re.I))
    explicit=bool(data.resource_ids or data.chapters or data.page_from or data.page_to or data.heading or chapter or position or overview)
    try:
        if explicit:
            scope=MaterialScope(resource_ids=data.resource_ids,chapters=data.chapters or ([chapter[1]] if chapter else []),page_from=data.page_from or (int(position[1]) if position else None),page_to=data.page_to or (int(position[2] or position[1]) if position else None),heading=data.heading)
            evidence=resolve(db,cid,scope,limit=None)
            from app.services.materials import spread
            chunks=spread(evidence,8) if overview else focus_evidence(evidence,question,k=8)
            retrieval_status=f'Selected teacher material: {len(chunks)} of {len(evidence)} excerpts used'
        else:
            chunks,retrieval_status=await run_in_threadpool(HybridStore().search,db,user,cid,question,k=8,teacher_only=data.teacher_only)
    except HTTPException as exc:
        if exc.status_code!=409:raise
        return {'answer':str(exc.detail),'sources':[],'mode':data.mode,'provider_status':'No retrieval result'}
    except ValueError as exc:raise HTTPException(422,str(exc))
    if not chunks:
        ready=db.scalar(select(Resource.id).where(Resource.course_id==cid,Resource.owner_id.is_(None),Resource.status=='ready').limit(1))
        message='The provided course material does not contain enough information to answer this confidently. '
        message+=('The course has indexed material, but no matching excerpt was found. Try the document, heading or slide range.' if ready else 'Check the current file status in Materials. Uploaded files may still be indexing or need readable text.')
        return {'answer':message,'sources':[],'mode':data.mode,'provider_status':'No retrieval result'}
    answer='';status='DEMO-SIMULATED' if DEMO_MODE else 'EXTRACTIVE FALLBACK'
    source_ids=[c['id'] for c in chunks]
    if not DEMO_MODE and os.getenv('LLM_API_KEY'):
        try:
            result=await asyncio.wait_for(CompatibleLLM().answer(data.question,chunks,data.mode),timeout=20)
            answer=result['answer'];source_ids=result['source_ids'];status='LIVE PROVIDER'
            if data.teacher_only or db.get(Course,cid).material_only:
                from app.ai.grounded import GroundingVerdict
                from app.ai.providers import structured_generation
                verdict=await asyncio.wait_for(structured_generation('Verify that every substantive claim in this tutor answer is supported by the provided sources. Reject external facts. Answer: '+answer,chunks,GroundingVerdict),timeout=15)
                if not verdict.supported or not set(verdict.source_ids)<={c['id'] for c in chunks}:answer='';raise ValueError('Answer support check failed.')
        except Exception as exc:
            logging.getLogger('campuspath.ai').warning('Tutor failed: %s',type(exc).__name__);answer='';status='EXTRACTIVE FALLBACK — provider unavailable, timed out or invalid output'
    if not answer:
        if data.mode=='Socratic Mode':answer='Read the excerpt below. Which rule applies, and why? Explain your reasoning before checking a worked solution.\n\n'+chunks[0]['text']
        elif data.mode=='Roman Urdu':answer='Yeh aap ke accessible course material ka relevant hissa hai. Offline mode mein nayi translation generate nahi hoti; sample bilingual notes hon to neeche dikhayi jati hain.\n\n'+chunks[0]['text']
        else:answer='From your course material:\n\n'+'\n\n'.join(c['text'] for c in chunks[:2])
    db.add(Conversation(student_id=user.id,course_id=cid,mode='tutor',question=data.question,answer=answer))
    profile=dict(user.profile or {});profile['mode']=data.mode;user.profile=profile;db.commit()
    return {'answer':answer,'sources':[c for c in chunks if c['id'] in source_ids],'provider_status':status,'retrieval_status':retrieval_status,'mode':data.mode}
def quiz_payload(db,run):
    if (run.settings or {}).get('practice_questions'):
        from app.ai.practice_quiz import practice_payload
        if run.expires<now() and not run.finished:run.finished=True;db.commit()
        return practice_payload(run)
    if run.finished or run.cursor>=len(run.question_ids) or run.expires<now():
        if not run.finished:run.finished=True;db.commit()
        from app.assessment.results import results
        return results(db,run)
    q=db.get(Question,run.question_ids[run.cursor])
    return {'id':run.id,'complete':False,'index':run.cursor,'total':len(run.question_ids),'expires':run.expires,'mode':run.mode,'coverage_notice':('Only '+str(len(run.question_ids))+' approved questions are available. This is a short practice check, not sufficient evidence of mastery. Ask your teacher to expand the bank.' if len(run.question_ids)<(run.settings or {}).get('requested_count',len(run.question_ids)) else ''),'question':{'id':q.id,'prompt':q.prompt,'options':q.options,'topic_id':q.topic_id,'difficulty':q.difficulty,'bloom':q.bloom}}
@router.post('/courses/{cid}/quiz',status_code=201)
async def start(cid:int,data:StartQuiz,user=Depends(current_user),db=Depends(get_db)):
    role(user,'student');course_access(db,user,cid)
    if data.material_based:
        from app.services.materials import MaterialScope,resolve
        from app.ai.practice_quiz import build_questions
        from app.auth.security import throttle
        if data.bloom_distribution or data.clo_distribution:raise HTTPException(422,'Bloom/CLO quotas are available only for the reviewed question bank.')
        scope=MaterialScope(resource_ids=data.resource_ids,chapters=data.chapters,page_from=data.page_from,page_to=data.page_to,heading=data.heading,topic_ids=([data.topic_id] if data.topic_id else data.topic_ids))
        evidence=resolve(db,cid,scope,limit=None)
        throttle(db,'practice-quiz:'+str(user.id),15)
        questions,provider=await build_questions(evidence,data.count,data.difficulty)
        if not questions:raise HTTPException(409,'Could not prepare reliable four-option questions within the generation time limit. Try fewer questions, a broader source range, or the reviewed question bank. No marks or questions were invented.')
        notice='' if len(questions)==data.count else f'Only {len(questions)} of {data.count} distinct source-supported questions could be prepared. Choose more material for a longer quiz.'
        run=QuizRun(student_id=user.id,course_id=cid,mode=data.mode,question_ids=[-i for i in range(1,len(questions)+1)],cursor=0,difficulty=1,settings={'practice_questions':questions,'practice_answers':{},'practice_provider':provider,'coverage_notice':notice,'total_marks':data.total_marks,'requested_count':data.count},hint_ids=[],question_started=now(),expires=now()+timedelta(minutes=data.minutes))
        db.add(run);db.commit();return quiz_payload(db,run)
    query=select(Question).where(Question.course_id==cid,Question.approved.is_(True))
    if data.topic_id:query=query.where(Question.topic_id==data.topic_id)
    if data.topic_ids:query=query.where(Question.topic_id.in_(data.topic_ids))
    if data.difficulty:query=query.where(Question.difficulty==data.difficulty)
    questions=db.scalars(query.order_by(Question.difficulty,Question.id)).all()
    if db.get(Course,cid).material_only:
        from app.models import Chunk,Resource
        allowed=set(db.scalars(select(Chunk.id).join(Resource,Resource.id==Chunk.resource_id).where(Resource.course_id==cid,Resource.owner_id.is_(None))))
        questions=[q for q in questions if q.source_ids and set(q.source_ids)<=allowed]
    if not questions:raise HTTPException(409,'No approved questions are available for this selection.')
    if data.mode=='mock':
        from app.assessment.selection import select_mock
        topics={t.id:t for t in db.scalars(select(Topic).where(Topic.course_id==cid))}
        questions=select_mock(questions,topics,data)
    if data.mode=='adaptive':
        # Retain multiple difficulties in the issued pool so correct responses can progress.
        order=[x['id'] for x in snapshot(db,user.id,cid)['path']]
        counts={}
        for qid in db.scalars(select(Answer.question_id).where(Answer.student_id==user.id)):
            counts[qid]=counts.get(qid,0)+1
        questions.sort(key=lambda q:(counts.get(q.id,0),order.index(q.topic_id) if q.topic_id in order else len(order),q.difficulty,q.id))
    # Diagnostic uses interleaving across concepts before repeated topics.
    if data.mode=='diagnostic':
        seen=set();first=[];rest=[]
        for q in questions:
            (rest if q.topic_id in seen else first).append(q);seen.add(q.topic_id)
        questions=first+rest
    run=QuizRun(student_id=user.id,course_id=cid,mode=data.mode,question_ids=[q.id for q in questions[:data.count]],cursor=0,difficulty=1,settings={'total_marks':data.total_marks,'minutes':data.minutes,'requested_count':data.count,'available_count':len(questions),'bloom_distribution':data.bloom_distribution,'clo_distribution':data.clo_distribution},hint_ids=[],question_started=now(),expires=now()+timedelta(minutes=data.minutes))
    db.add(run);db.commit();return quiz_payload(db,run)
@router.get('/quiz/{rid}')
def get_quiz(rid:int,user=Depends(current_user),db=Depends(get_db)):
    run=db.get(QuizRun,rid)
    if not run or run.student_id!=user.id:raise HTTPException(404,'Assessment not found.')
    course_access(db,user,run.course_id)
    return quiz_payload(db,run)
@router.post('/quiz/{rid}/answer')
def answer(rid:int,data:AnswerInput,user=Depends(current_user),db=Depends(get_db)):
    role(user,'student');run=db.get(QuizRun,rid)
    if not run or run.student_id!=user.id:raise HTTPException(404,'Assessment not found.')
    course_access(db,user,run.course_id)
    if run.finished:raise HTTPException(409,'Assessment is already complete.')
    if run.expires<now():raise HTTPException(409,'Assessment time has expired. Start a new attempt.')
    if run.cursor>=len(run.question_ids) or data.question_id!=run.question_ids[run.cursor]:raise HTTPException(409,'This question was already answered or is not currently issued.')
    if (run.settings or {}).get('practice_questions'):
        cursor=run.cursor;settings=dict(run.settings);q=settings['practice_questions'][cursor]
        if data.selected>=len(q['options']):raise HTTPException(422,'Invalid answer option.')
        answers=dict(settings.get('practice_answers',{}));answers[str(cursor)]=data.selected;settings['practice_answers']=answers
        claim=db.execute(update(QuizRun).where(QuizRun.id==rid,QuizRun.cursor==cursor,QuizRun.finished.is_(False),QuizRun.expires>now()).values(cursor=cursor+1,settings=settings,finished=cursor+1>=len(run.question_ids),question_started=now()))
        if claim.rowcount!=1:db.rollback();raise HTTPException(409,'Answer already processed or session expired.')
        db.commit();db.refresh(run)
        if run.mode=='mock':return {'saved':True,'feedback_delayed':True,'next':quiz_payload(db,run)}
        return {'correct':data.selected==q['correct'],'correct_answer':q['options'][q['correct']],'explanation':q['explanation'],'sources':q['sources'],'next':quiz_payload(db,run)}
    q=db.get(Question,data.question_id)
    if data.selected>=len(q.options):raise HTTPException(422,'Invalid answer option.')
    cursor=run.cursor
    claimed=db.execute(update(QuizRun).where(QuizRun.id==rid,QuizRun.cursor==cursor,QuizRun.finished.is_(False)).values(cursor=cursor+1))
    if claimed.rowcount!=1:db.rollback();raise HTTPException(409,'Answer already processed.')
    correct=data.selected==q.correct
    impact=observe(db,user,q,correct,run,data.selected)
    run.difficulty=next_difficulty(q.difficulty,correct)
    run.question_started=now()
    ids=list(run.question_ids)
    if run.mode=='adaptive':
        remaining=ids[cursor+1:]
        remaining.sort(key=lambda qid:abs(db.get(Question,qid).difficulty-run.difficulty))
        run.question_ids=ids[:cursor+1]+remaining
    try:db.commit()
    except IntegrityError:db.rollback();raise HTTPException(409,'Answer already processed.')
    if run.mode=='mock' and not run.finished and run.cursor<len(run.question_ids):
        return {'saved':True,'feedback_delayed':True,'next':quiz_payload(db,run)}
    return {'correct':correct,'correct_answer':q.options[q.correct],'explanation':teaching_feedback(db,q,data.selected),'possible_misconception':q.misconception if not correct else None,'mastery':impact,'next':quiz_payload(db,run)}
@router.post('/revisions/{rid}/complete')
def revision(rid:int,user=Depends(current_user),db=Depends(get_db)):
    role(user,'student');r=db.get(Revision,rid)
    if not r or r.student_id!=user.id:raise HTTPException(404,'Revision not found.')
    course_access(db,user,db.get(Topic,r.topic_id).course_id)
    r.done=True;db.commit();return {'ok':True,'message':'Revision marked complete. Take a quiz to provide new mastery evidence.'}
@router.post('/courses/{cid}/planner')
def plan(cid:int,data:PlanInput,user=Depends(current_user),db=Depends(get_db)):
    role(user,'student');course_access(db,user,cid)
    from app.services.planning import create_plan
    return create_plan(db,user,cid,data)
@router.get('/algorithm/{name}')
def algorithm(name:str,user=Depends(current_user)):
    try:return algorithm_steps(name)
    except ValueError as e:raise HTTPException(422,str(e))
@router.post('/courses/{cid}/viva')
def viva(cid:int,data:TextInput,user=Depends(current_user),db=Depends(get_db)):
    role(user,'student');course_access(db,user,cid)
    if not DEMO_MODE:raise HTTPException(404,'Legacy demonstration is disabled. Use the material-grounded viva workflow.')
    from sample_data.legacy_viva import evaluate_demo
    return evaluate_demo(db,user,cid,data)

@router.post('/quiz/{rid}/finish')
def finish_quiz(rid:int,user=Depends(current_user),db=Depends(get_db)):
    run=db.get(QuizRun,rid)
    if not run or run.student_id!=user.id:raise HTTPException(404,'Assessment not found.')
    course_access(db,user,run.course_id);run.finished=True;db.commit();return quiz_payload(db,run)
@router.post('/quiz/{rid}/hint')
def hint(rid:int,user=Depends(current_user),db=Depends(get_db)):
    run=db.get(QuizRun,rid)
    if not run or run.student_id!=user.id:raise HTTPException(404,'Assessment not found.')
    course_access(db,user,run.course_id)
    if run.mode=='mock':raise HTTPException(403,'Hints are unavailable during a mock exam.')
    if run.finished or run.expires<now() or run.cursor>=len(run.question_ids):raise HTTPException(409,'This assessment is no longer active.')
    if (run.settings or {}).get('practice_questions'):
        return {'hint':'Recall the concept and compare each option with the rule in your selected material.','message':'Personal practice hint; official mastery is unchanged.'}
    qid=run.question_ids[run.cursor];q=db.get(Question,qid)
    run.hint_ids=list(set((run.hint_ids or [])+[qid]));db.commit()
    return {'hint':db.get(Topic,q.topic_id).description,'message':'This is assisted practice; a correct answer will have reduced weight in the knowledge model.'}
@router.get('/courses/{cid}/assessments')
def history(cid:int,user=Depends(current_user),db=Depends(get_db)):
    role(user,'student');course_access(db,user,cid)
    return [{'id':r.id,'mode':r.mode,'created':r.created,'expires':r.expires,'complete':r.finished or r.cursor>=len(r.question_ids) or r.expires<now(),'answered':r.cursor,'total':len(r.question_ids),'material_based':bool((r.settings or {}).get('practice_questions'))} for r in db.scalars(select(QuizRun).where(QuizRun.student_id==user.id,QuizRun.course_id==cid).order_by(QuizRun.id.desc()).limit(30))]
