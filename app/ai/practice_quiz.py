"""Private source-grounded MCQs. Offline questions require explicit source facts."""
import re, asyncio, logging
from secrets import SystemRandom
from app.ai import grounded
from app.services.materials import spread


def offline_questions(evidence, count, difficulty=None):
    # Extract explicit term/definition pairs and expansions. Options are actual source terms,
    # never invented facts. Do not make a question when the source cannot disambiguate it.
    facts = []
    for src in evidence:
        text = src['text']
        for line in re.split(r'\n|(?<=[.!?])\s+', text):
            line = line.strip(' \t•–—-')
            m = re.match(r'^([A-Za-z][\w /-]{1,70}?)\s+(?:is defined as|refers to|means|is|are|describes|uses|performs)\s+(.{12,220})$', line, re.I)
            if m:
                term, definition = m[1].strip(), m[2].strip(' .;')
                if len(term.split()) <= 8 and len(definition.split()) >= 3 and term.casefold() not in definition.casefold():
                    facts.append((term, definition, src))
        for m in re.finditer(r'\b([A-Z][A-Za-z-]*(?:\s+[A-Za-z-]+){1,7})\s*\(([A-Z][A-Z0-9]{1,9})\)', text):
            words=re.findall(r'[A-Za-z]+',m[1])
            initials=''.join(w[0].upper() for w in words)
            if initials.endswith(m[2]):
                expansion=' '.join(words[-len(m[2]):]); facts.append((m[2], expansion, src))
    unique={}
    for term,definition,src in facts:
        unique.setdefault(term.casefold(),(term,definition,src))
    rng=SystemRandom(); pool=list(unique.values()); rng.shuffle(pool)
    items=[]; seen=set()
    if difficulty not in (None,1):return []  # no false claims about advanced difficulty
    for term,definition,src in pool:
        if definition.casefold() in seen:continue
        # Reject competing terms with the same or overlapping definition.
        others=[t for t,d,_ in pool if t!=term and d.casefold()!=definition.casefold() and t.casefold() not in definition.casefold() and definition.casefold() not in d.casefold()]
        if len(others)<3:continue
        options=[term]+rng.sample(others,3);rng.shuffle(options)
        items.append({'prompt':f'Which term matches this description: {definition}?','options':options,'correct':options.index(term),'explanation':f'{term}: {definition}.','difficulty':1,'bloom':'Remember','topic':src.get('structure',{}).get('heading') or term,'sources':[{'id':src['id'],'filename':src['filename'],'location':src['location']} ]})
        seen.add(definition.casefold())
        if len(items)==count:break
    return items


async def build_questions(evidence, count, difficulty=None):
    if grounded.enabled():
        selected=spread(evidence,min(len(evidence),max(12,count*2)))
        try:
            drafts,provider=await asyncio.wait_for(grounded.questions(selected,[],{'count':count,'total_marks':count,'personal_practice':True,'difficulty':str(difficulty) if difficulty else 'Mixed','question_types':['MCQ'],'bloom_distribution':{},'coverage_instruction':'Exactly four distinct plausible options and one defensible correct answer. Use concise self-contained exam-style stems, no pasted source paragraphs or file names. Explain why the correct answer fits the material. Test different concepts.'}),timeout=45)
            mapping={s['id']:s for s in selected};items=[]
            for q in drafts:
                if q.question_type!='MCQ' or len(q.options)!=4 or len({x.strip().casefold() for x in q.options})!=4 or any(not x.strip() for x in q.options):raise ValueError('Invalid MCQ choices')
                if q.correct_option is None or not 0<=q.correct_option<4:raise ValueError('Invalid key')
                if len(q.question_text)>400:raise ValueError('Question is not concise')
                sources=grounded.validate_citations(q.citations,selected)
                items.append({'prompt':q.question_text,'options':q.options,'correct':q.correct_option,'explanation':' '.join(q.acceptable_answer_points),'difficulty':q.difficulty,'bloom':q.bloom,'topic':sources[0].get('structure',{}).get('heading') or 'Course material','sources':[{'id':s['id'],'filename':s['filename'],'location':s['location']} for s in sources]})
            if items:return items,provider
        except Exception as exc:
            logging.getLogger('campuspath.ai').warning('Practice quiz generation failed: %s',type(exc).__name__)
    return offline_questions(evidence,count,difficulty),'OFFLINE SOURCE PRACTICE'


def practice_payload(run):
    settings=run.settings; questions=settings['practice_questions']; answers=settings.get('practice_answers',{}); count=len(questions)
    complete=run.finished or run.cursor>=count
    result={'id':run.id,'complete':complete,'index':run.cursor,'total':count,'expires':run.expires,'mode':run.mode,'material_based':True,'provider':settings['practice_provider'],'coverage_notice':settings.get('coverage_notice','')}
    if not complete:
        q=questions[run.cursor]
        result['question']={k:q[k] for k in ('prompt','options','difficulty','bloom')};result['question']['id']=-(run.cursor+1)
        return result
    correct=0;details=[];topics={}
    for i,q in enumerate(questions):
        chosen=answers.get(str(i));ok=chosen is not None and chosen==q['correct'];correct+=ok
        topics.setdefault(q['topic'],[]).append(ok)
        details.append({'id':-(i+1),'prompt':q['prompt'],'answered':chosen is not None,'correct':ok,'your_answer':q['options'][chosen] if chosen is not None else None,'correct_answer':q['options'][q['correct']],'explanation':q['explanation'],'sources':q['sources'],'topic':q['topic'],'clo':'Personal practice','bloom':q['bloom']})
    marks=settings['total_marks'];result.update(score=round(100*correct/count),marks=round(marks*correct/count,2),total_marks=marks,answered=len(answers),unanswered=count-len(answers),details=details,topic_results={k:round(100*sum(v)/len(v)) for k,v in topics.items()},clo_results={},time_used_seconds=0)
    return result
