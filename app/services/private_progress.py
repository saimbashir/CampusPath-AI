"""Observed student practice, scoped to the signed-in student and course."""
from sqlalchemy import select
from app.models import QuizRun, Answer, Question, Topic, VivaTurn, VivaSession
from app.services.official_progress import avg,visible_topic
from app.knowledge_graph.engine import learning_order

def private_progress(db,sid,cid,result):
    topics={t.id:t for t in db.scalars(select(Topic).where(Topic.course_id==cid)) if visible_topic(t)}
    sources={tid:set((t.structure or {}).get('source_ids',[])) for tid,t in topics.items()}
    observed={};values=[];bloom={};mistakes=[]
    for a,q in db.execute(select(Answer,Question).join(Question,Question.id==Answer.question_id).join(QuizRun,QuizRun.id==Answer.run_id).where(Answer.student_id==sid,QuizRun.student_id==sid,QuizRun.course_id==cid,Question.course_id==cid)):
        score=100*int(a.correct);values.append(score);observed.setdefault(q.topic_id,[]).append(score);bloom.setdefault(q.bloom,[]).append(score)
        if not a.correct:mistakes.append({'topic_id':q.topic_id,'evidence':q.explanation,'created':a.created})
    runs=list(db.scalars(select(QuizRun).where(QuizRun.student_id==sid,QuizRun.course_id==cid)))
    for run in runs:
        cfg=run.settings or {};qs=cfg.get('practice_questions',[])
        for index,choice in cfg.get('practice_answers',{}).items():
            if not str(index).isdigit() or int(index)>=len(qs):continue
            q=qs[int(index)];score=100*int(choice==q['correct']);values.append(score);bloom.setdefault(q.get('bloom','Understand'),[]).append(score)
            if not score:mistakes.append({'topic_id':None,'evidence':q['explanation'],'created':run.created})
            cited={s['id'] for s in q.get('sources',[])}
            matched=[tid for tid,ids in sources.items() if cited & ids]
            if not matched:
                matched=[tid for tid,t in topics.items() if t.name.casefold()==str(q.get('topic','')).casefold()]
            for tid in matched:observed.setdefault(tid,[]).append(score)
    outcomes={}
    for t in result['topics']:
        scores=observed.get(t['id'],[]);t['mastery']=avg(scores);t['attempts']=len(scores);t['confidence']=min(1,len(scores)/12);t['prerequisites']=[p for p in t['prerequisites'] if p in topics]
        t['chapter']=(topics[t['id']].structure or {}).get('chapter','')
        if scores:outcomes.setdefault(t['clo'],[]).extend(scores)
    result['path']=[]
    for topic in learning_order(list(topics.values()),{tid:(avg(scores) or 0)/100 for tid,scores in observed.items() if tid in topics}):
        scores=observed.get(topic.id,[]);result['path'].append({'id':topic.id,'name':topic.name,'why':f'{avg(scores)}% correct in recorded practice.' if scores else 'Not assessed yet. Study this concept and its prerequisites.','confidence':min(1,len(scores)/12)})
    result['mastery']=avg(values);result['quiz_average']=avg(values);result['attempts']=len(values);result['clos']={k:avg(v) for k,v in outcomes.items()};result['bloom']={k:avg(v) for k,v in bloom.items()};result['readiness']=None;result['trend']=None
    result['readiness_detail']={'score':None,'factors':[],'methodology':'Observed quiz accuracy, not a predicted grade. Unassessed concepts have no score. Only source-linked or exactly matched practice updates a concept.'}
    result['readiness_factors']={'components':[],'coverage':None,'accuracy':avg(values),'methodology':result['readiness_detail']['methodology']}
    turns=list(db.scalars(select(VivaTurn).join(VivaSession,VivaSession.id==VivaTurn.session_id).where(VivaSession.student_id==sid,VivaSession.course_id==cid)))
    result['private_practice']={'quiz_sessions':len(runs),'quiz_answers':len(values),'viva_answers':len(turns),'viva_ai_average':avg([t.proposed_score for t in turns if t.proposed_score is not None])}
    result['viva_average']=result['private_practice']['viva_ai_average'];result['viva_reviewed_count']=0
    result['status']='NOT ASSESSED' if not values else 'RECORDED PRACTICE'
    result['misconceptions']=sorted(mistakes,key=lambda m:m['created'],reverse=True)[:30]
    result['history']=[]  # legacy posterior history mixes official and practice assessments
    result['revisions']=[r for r in result['revisions'] if r['topic_id'] in topics]
    return result
