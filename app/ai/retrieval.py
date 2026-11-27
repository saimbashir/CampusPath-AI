import re,math
from collections import Counter
from sqlalchemy import select, or_
from app.models import Resource,Chunk,Course,Topic
STOP={'the','a','an','in','to','of','and','is','it','what','explain','according','mein','mujhe','karo','roman','urdu','lecture','does','how','why','which','please','me','from','between','difference','about','give','tell','with','using','can','you','this','that','are','ka','ki','ke','hai','hain','kya','kaisay','kaise','samjhao','samjhayen'}
def tokens(text):
    text=text.lower()
    return [x for x in re.findall(r'[\w]+(?:[*+#]+)?',text) if x not in STOP]
class LexicalStore:
    """Offline BM25-like ranking. Authorize resources before computing scores."""
    def search(self,db,user,course_id,query,k=4,teacher_only=False):
        rows=db.execute(select(Chunk,Resource).join(Resource,Chunk.resource_id==Resource.id).where(Resource.course_id==course_id,Resource.status=='ready',Resource.owner_id.is_(None) if teacher_only or db.get(Course,course_id).material_only else or_(Resource.owner_id.is_(None),Resource.owner_id==user.id))).all()
        # Derive abbreviations from current teacher text and topic names (GBFS -> Greedy Best-First Search).
        q=set(tokens(query));scored=[]
        phrases=[t.name for t in db.scalars(select(Topic).where(Topic.course_id==course_id))]
        for c,r in rows:
            phrases.extend(re.findall(r'\b(?:[A-Z][a-z]+(?:[- ]|$)){2,6}',c.text))
        for phrase in phrases:
            words=re.findall(r'[A-Za-z]+',phrase)
            initials=''.join(w[0] for w in words).lower()
            if len(initials)>=2 and (initials in q or initials+'s' in q):q.update(tokens(phrase))
        corpus=[Counter(tokens(c.text)) for c,r in rows]
        frequencies={term:sum(term in doc for doc in corpus) for term in q}
        for (c,r),words in zip(rows,corpus):
            score=0
            for term in q:
                tf=words[term]
                df=frequencies[term]
                score+=math.log(1+(len(rows)-df+0.5)/(df+0.5))*tf*2.2/(tf+1.2) if tf else 0
            if score>0:scored.append({'id':c.id,'filename':r.filename,'location':c.location,'text':c.text,'score':round(score,4),'_teacher':r.owner_id is None})
        ranked=sorted(scored,key=lambda c:(c['_teacher'],c['score']),reverse=True)[:k]
        for item in ranked:item.pop('_teacher')
        return ranked

def focus_evidence(evidence,query,k=8):
    words=set(tokens(query));ranked=[]
    for i,source in enumerate(evidence):
        score=len(words & set(tokens(source['text']+' '+source['filename']+' '+str(source.get('structure',{}).get('heading','')))))
        ranked.append((score,i,source))
    relevant=[x for x in ranked if x[0]>0]
    if relevant:
        selected=sorted(relevant,key=lambda x:(-x[0],x[1]))[:k]
        return [x[2] for x in sorted(selected,key=lambda x:x[1])]
    from app.services.materials import spread
    return spread(evidence,k)

class HybridStore:
    def search(self,db,user,course_id,query,k=4,teacher_only=False):
        from app.ai.vector import enabled,QdrantStore
        lexical=LexicalStore().search(db,user,course_id,query,k=k,teacher_only=teacher_only)
        if not enabled():return lexical,'Lexical offline retrieval'
        rows=db.execute(select(Chunk,Resource).join(Resource,Chunk.resource_id==Resource.id).where(Resource.course_id==course_id,Resource.status=='ready',Resource.owner_id.is_(None) if teacher_only or db.get(Course,course_id).material_only else or_(Resource.owner_id.is_(None),Resource.owner_id==user.id))).all()
        mapping={c.id:{'id':c.id,'filename':r.filename,'location':c.location,'text':c.text} for c,r in rows}
        try:
            semantic=QdrantStore().search(query,list(mapping),k=k*2)
            scores={}
            for ranking in ([r['id'] for r in lexical],semantic):
                for rank,cid in enumerate(ranking):scores[cid]=scores.get(cid,0)+1/(60+rank+1)
            result=[dict(mapping[cid],score=round(score,5)) for cid,score in sorted(scores.items(),key=lambda x:x[1],reverse=True)[:k] if cid in mapping]
            return result,'Hybrid lexical + semantic retrieval'
        except Exception:return lexical,'Lexical fallback — semantic service unavailable'
