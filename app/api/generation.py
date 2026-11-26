from fastapi import APIRouter,Depends,HTTPException
from pydantic import BaseModel,Field
from sqlalchemy import select
from app.db import get_db
from app.models import Resource,Chunk,Topic,Question
from app.ai.curriculum import CurriculumDraft,QuestionDraft
from app.ai.providers import structured_generation
from app.auth.security import current_user,course_access,audit,throttle
from app.knowledge_graph.engine import validate_dag
from app.config import DEMO_MODE
router=APIRouter(prefix='/api/courses')
def evidence(db,cid,limit=300):
    rows=db.execute(select(Chunk,Resource).join(Resource,Resource.id==Chunk.resource_id).where(Resource.course_id==cid,Resource.owner_id.is_(None)).order_by(Resource.id,Chunk.id).limit(limit)).all()
    if not rows:raise HTTPException(409,'Upload course material first.')
    return [{'id':c.id,'text':c.text,'filename':r.filename,'location':c.location} for c,r in rows]
def focus(context,text,n):
    """The n excerpts most related to a topic (simple word overlap), in book order."""
    from app.ai.retrieval import tokens
    words=set(tokens(text))
    if len(context)<=n or not words:return context[:n]
    ranked=sorted(range(len(context)),key=lambda i:-len(words & set(tokens(context[i]['text']))))[:n]
    return [context[i] for i in sorted(ranked)]
@router.post('/{cid}/curriculum/draft')
async def curriculum(cid:int,user=Depends(current_user),db=Depends(get_db)):
    course=course_access(db,user,cid,True);throttle(db,'generation:'+str(user.id),15)
    if DEMO_MODE:raise HTTPException(503,'AI generation requires a configured provider and DEMO_MODE=false. You can manually edit the course structure offline.')
    context=evidence(db,cid)
    existing=list(db.scalars(select(Topic.name).where(Topic.course_id==cid)).all())
    from app.config import LLM_EXCERPTS_PER_CALL
    from app.ai.curriculum import DraftTopic
    found={};failed=0
    # Read the WHOLE uploaded material in small groups (free AI plans reject huge prompts).
    for start in range(0,len(context),LLM_EXCERPTS_PER_CALL):
        batch=context[start:start+LLM_EXCERPTS_PER_CALL]
        try:draft=await structured_generation('Extract NEW course topics, definitions and prerequisite relationships from these excerpts. Use prerequisite names. Avoid existing topics: '+str(existing+list(found))+'. Align to these CLOs: '+str(course.clos),batch,CurriculumDraft)
        except Exception:
            failed+=1;continue
        for t in draft.topics:
            if t.name not in found and t.name not in existing:found[t.name]=t
        if len(found)>=40:break
    if not found:raise HTTPException(503,'Generation failed or returned invalid structured output. Try again or author topics manually.')
    names=set(found)|set(existing)
    topics=[DraftTopic(**{**t.model_dump(),'prerequisites':[p for p in t.prerequisites if p in names and p!=t.name]}) for t in list(found.values())[:40]]
    try:result=CurriculumDraft(topics=topics)
    except ValueError:result=CurriculumDraft(topics=[DraftTopic(**{**t.model_dump(),'prerequisites':[]}) for t in topics])
    return {'draft':result.model_dump(),'review_required':True,'sources':context,'skipped_groups':failed}
@router.post('/{cid}/curriculum/approve')
def approve_curriculum(cid:int,data:CurriculumDraft,user=Depends(current_user),db=Depends(get_db)):
    course_access(db,user,cid,True)
    existing=db.scalars(select(Topic).where(Topic.course_id==cid)).all();mapping={t.name:t for t in existing}
    if any(t.name in mapping for t in data.topics):raise HTTPException(409,'A topic name already exists. Edit the existing topic instead.')
    for t in data.topics:
        row=Topic(course_id=cid,name=t.name,description=t.description,clo=t.clo,difficulty=t.difficulty,prerequisites=[]);db.add(row);db.flush();mapping[t.name]=row
    for t in data.topics:
        if any(p not in mapping for p in t.prerequisites):db.rollback();raise HTTPException(422,'Unknown prerequisite name in draft.')
        mapping[t.name].prerequisites=[mapping[p].id for p in t.prerequisites]
    try:validate_dag(list(mapping.values()))
    except ValueError as exc:db.rollback();raise HTTPException(422,str(exc))
    audit(db,user,'curriculum approved',cid);db.commit();return {'created':len(data.topics)}
class GenerationInput(BaseModel):
    topic_id:int
    resource_ids:list[int]=[]
    chapters:list[str]=[]
@router.post('/{cid}/questions/generate')
async def generate_question(cid:int,data:GenerationInput,user=Depends(current_user),db=Depends(get_db)):
    course_access(db,user,cid,True);throttle(db,'generation:'+str(user.id),15)
    topic=db.get(Topic,data.topic_id)
    if not topic or topic.course_id!=cid:raise HTTPException(404,'Topic not found.')
    if DEMO_MODE:raise HTTPException(503,'Question generation requires a configured provider and DEMO_MODE=false. The offline teacher editor is available.')
    from app.services.materials import MaterialScope,resolve
    if data.resource_ids or data.chapters:
        context=resolve(db,cid,MaterialScope(resource_ids=data.resource_ids,chapters=data.chapters),limit=40)
    elif (topic.structure or {}).get('source_ids'):
        context=resolve(db,cid,MaterialScope(chunk_ids=topic.structure['source_ids']),limit=40)
    else:
        context=evidence(db,cid)
    from app.config import LLM_EXCERPTS_PER_CALL
    context=focus(context,topic.name+' '+(topic.description or ''),LLM_EXCERPTS_PER_CALL)
    try:draft=await structured_generation(f'Create one unambiguous multiple-choice question for topic {topic.name}, topic_id={topic.id}. Give the zero-based correct option index, evidence-based explanation, misconception, Bloom level and difficulty 1–3. Cite provided source IDs. Do not use evidence from unrelated topics.',context,QuestionDraft)
    except Exception:raise HTTPException(503,'Generation failed validation. Write the question manually or try again.')
    mapping={c['id']:c for c in context}
    if draft.question.topic_id!=topic.id or not set(draft.source_ids)<=mapping.keys():raise HTTPException(502,'Generated topic or citation failed validation.')
    if db.scalar(select(Question.id).where(Question.course_id==cid,Question.prompt==draft.question.prompt)):raise HTTPException(409,'Generated question duplicates an existing question.')
    source=mapping[draft.source_ids[0]]
    draft.question.source_ids=draft.source_ids
    draft.question.source=f"AI GENERATED · {source['filename']} · {source['location']}"[:200]
    return {'draft':draft.question.model_dump(),'review_required':True,'checks':['Valid option count','Valid answer index','No exact duplicate','Source IDs authorized','Topic matches request'],'sources':[mapping[i] for i in draft.source_ids],'limitation':'Correctness, ambiguity and Bloom alignment still require teacher judgment.'}

class BatchGenerationInput(GenerationInput):
    count:int=Field(default=10,ge=4,le=20)

@router.post('/{cid}/questions/generate-batch',status_code=201)
async def generate_batch(cid:int,data:BatchGenerationInput,user=Depends(current_user),db=Depends(get_db)):
    course_access(db,user,cid,True);throttle(db,'generation:'+str(user.id),15)
    topic=db.get(Topic,data.topic_id)
    if not topic or topic.course_id!=cid:raise HTTPException(404,'Topic not found.')
    from app.ai import grounded
    from app.services.materials import MaterialScope,resolve
    if not grounded.enabled():raise HTTPException(503,'Configure the language-model provider to generate a varied question bank. Teacher-authored questions remain available.')
    scope=MaterialScope(resource_ids=data.resource_ids,chapters=data.chapters)
    if not data.resource_ids and not data.chapters and (topic.structure or {}).get('source_ids'):scope.chunk_ids=topic.structure['source_ids']
    context=resolve(db,cid,scope)
    config={'count':data.count,'total_marks':data.count,'difficulty':'Mixed','question_types':['MCQ'],'bloom_distribution':{},'force_topic_id':topic.id,'coverage_instruction':'Cover distinct definitions, relationships, applications, examples, boundary cases and misconceptions actually supported by the material. Do not paraphrase the same fact repeatedly. Explain the correct rule and why distractors fail in simple language.'}
    existing=set(db.scalars(select(Question.prompt).where(Question.course_id==cid)))
    try:
        # grounded.questions keeps only questions that pass every check and keeps asking
        # (in small requests) until the requested number is reached.
        drafts,provider=await grounded.questions(context,[{'id':topic.id,'name':topic.name,'description':topic.description,'source_ids':(topic.structure or {}).get('source_ids',[])}],config,existing_prompts=list(existing))
        prompts=set()
        for q in drafts:
            if len(set(q.options))!=len(q.options) or any(not o.strip() for o in q.options) or q.question_type!='MCQ' or q.topic_id!=topic.id or q.question_text in existing or q.question_text.casefold() in prompts:raise ValueError('Invalid topic/type or duplicate question.')
            prompts.add(q.question_text.casefold())
        for q in drafts:
            explanation=' '.join(q.acceptable_answer_points)
            db.add(Question(course_id=cid,topic_id=topic.id,prompt=q.question_text,options=q.options,correct=q.correct_option,explanation=explanation,misconception='; '.join(q.possible_misconceptions),difficulty=q.difficulty,bloom=q.bloom,approved=False,source='AI material-grounded batch; teacher review required',source_ids=[c.chunk_id for c in q.citations]))
        audit(db,user,'question batch drafted',cid);db.commit()
    except Exception as exc:
        db.rollback()
        detail=str(exc) if isinstance(exc,ValueError) and 'questions passed' in str(exc) else 'The batch failed source, topic or duplicate validation.'
        raise HTTPException(502,detail+' No questions were saved. Try a smaller batch or narrower material selection.')
    return {'created':len(drafts),'review_required':True,'message':'Review and approve each draft in the question bank before students can use it.'}
