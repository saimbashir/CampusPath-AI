"""Subject-independent scope resolution and source metadata. No subject-specific templates."""
import re
from sqlalchemy import select
from fastapi import HTTPException
from app.models import Chunk,Resource,Topic
from app.schemas import Input
from pydantic import Field
class MaterialScope(Input):
    resource_ids:list[int]=Field(default_factory=list,max_length=100)
    chunk_ids:list[int]=Field(default_factory=list,max_length=300)
    topic_ids:list[int]=Field(default_factory=list,max_length=100)
    chapters:list[str]=Field(default_factory=list,max_length=100)
    units:list[str]=Field(default_factory=list,max_length=100)
    sections:list[str]=Field(default_factory=list,max_length=100)
    clos:list[str]=Field(default_factory=list,max_length=40)
    page_from:int|None=Field(default=None,ge=1)
    page_to:int|None=Field(default=None,ge=1)

# Heading patterns that work for any subject. Labels always come from the file itself.
CLASSIC=re.compile(r'^(chapter|unit|section)\s+([\w.\-]+)(?:\s*[:—\-]?\s*)(.*)$',re.I)
KEYWORD=re.compile(r'^(lesson|module|lecture|week|part|topic)\s+(\d+(?:\.\d+)*|[IVXLC]+)\b\s*[:—–\-.]?\s*(.*)$',re.I)
NAMED=re.compile(r'^(chapter|unit|section):\s+(.{2,100})$',re.I)          # Word "Heading 1/2" styles
NUMBERED=re.compile(r'^(\d{1,2})\.(\d{1,2})(?:\.\d{1,2})*\.?\s+([A-Z][^\n]{2,90})$')  # "4.2 Binary Trees"
KIND={'chapter':'chapter','lesson':'chapter','lecture':'chapter','week':'chapter','unit':'unit','module':'unit','part':'unit','section':'section','topic':'section'}

def heading(line):
    """Return (kind, label, title) when a line is a structural heading, else None."""
    title=line.strip().lstrip('#').strip()
    if not title or len(title)>120:return None
    m=CLASSIC.match(title)
    if m:return m[1].lower(),m[2].rstrip('.:'),title
    m=KEYWORD.match(title)
    if m:return KIND[m[1].lower()],m[2].rstrip('.'),title
    m=NAMED.match(title)
    if m:return m[1].lower(),m[2].strip()[:60],title
    m=NUMBERED.match(title)
    # Skip table-of-contents lines ("4.2 Binary Trees ........ 87") and full sentences.
    if m and not re.search(r'(\.{3,}|\s\d+)$',title) and not title.endswith('.') and len(title.split())<=12:
        return 'numbered',m[1]+'.'+m[2],title
    return None

def annotated(parts,filename,outline=None):
    """Yield (location, excerpt, structure) with book/unit/chapter/section/page labels.

    outline: optional {page: bookmark title} from the PDF, used as chapter labels when
    the page text itself has no recognisable chapter heading."""
    from app.documents.extract import split_text
    state={'book':filename};outline=outline or {}
    for location,text in parts:
        page=re.match(r'Page (\d+)',location);state['page']=int(page[1]) if page else None
        if state['page'] in outline:
            title=outline[state['page']];number=re.search(r'\b(\d+)\b',title)
            state['chapter']=number[1] if number else title[:60];state['chapter_title']=title
            state.pop('section',None);state.pop('section_title',None)
        segments=[];current=[]
        for line in text.splitlines():
            found=heading(line)
            if found:
                if current:segments.append((dict(state),'\n'.join(current)));current=[]
                kind,label,title=found
                if kind=='numbered':
                    chapter=label.split('.')[0]
                    if str(state.get('chapter','')).isdigit() or 'chapter' not in state:
                        if state.get('chapter')!=chapter:state['chapter']=chapter;state.pop('chapter_title',None)
                    kind='section'
                state[kind]=label;state[kind+'_title']=title
                if kind in ('unit','chapter'):
                    state.pop('section',None);state.pop('section_title',None)
                if kind=='unit':state.pop('chapter',None);state.pop('chapter_title',None)
            current.append(line)
        if current:segments.append((dict(state),'\n'.join(current)))
        for meta,body in segments:
            for piece in split_text(body):
                if piece.strip():yield location,piece.strip(),meta

def resolve(db,cid,scope,limit=300):
    """All selectors combine by intersection; omitted selectors mean all teacher material."""
    if isinstance(scope,dict):scope=MaterialScope.model_validate(scope)
    rows=db.execute(select(Chunk,Resource).join(Resource,Resource.id==Chunk.resource_id).where(Resource.course_id==cid,Resource.owner_id.is_(None)).order_by(Resource.id,Chunk.id)).all()
    valid_resources={r.id for c,r in rows};valid_chunks={c.id for c,r in rows}
    if not set(scope.resource_ids)<=valid_resources or not set(scope.chunk_ids)<=valid_chunks:raise HTTPException(422,'Scope contains inaccessible or unindexed teacher material.')
    topics=db.scalars(select(Topic).where(Topic.course_id==cid)).all()
    if not set(scope.topic_ids)<={t.id for t in topics}:raise HTTPException(422,'Topics must belong to this course.')
    selected=[t for t in topics if (not scope.topic_ids or t.id in scope.topic_ids) and (not scope.clos or t.clo in scope.clos)]
    if scope.topic_ids or scope.clos:
        source_ids=set(i for t in selected for i in (t.structure or {}).get('source_ids',[]))
        if not source_ids:raise HTTPException(422,'Selected topics/CLOs need source links. Extract the digital twin or edit the topic source mapping first.')
    else:source_ids=None
    result=[]
    for c,r in rows:
        m=c.structure or {}
        if scope.resource_ids and r.id not in scope.resource_ids:continue
        if scope.chunk_ids and c.id not in scope.chunk_ids:continue
        if source_ids is not None and c.id not in source_ids:continue
        if any(values and str(m.get(key,'')) not in values for key,values in [('chapter',scope.chapters),('unit',scope.units),('section',scope.sections)]):continue
        if scope.page_from and (not m.get('page') or m['page']<scope.page_from):continue
        if scope.page_to and (not m.get('page') or m['page']>scope.page_to):continue
        result.append({'id':c.id,'resource_id':r.id,'filename':r.filename,'location':c.location,'text':c.text,'structure':m})
    if not result:raise HTTPException(409,'The provided course material does not contain enough information to answer this confidently. No excerpts match the selected scope.')
    if len(result)>limit:raise HTTPException(422,f'Scope contains {len(result)} excerpts; select a chapter or documents with at most {limit} excerpts for this operation.')
    return result

_FOLD=str.maketrans({'‘':"'",'’':"'",'“':'"','”':'"','–':'-','—':'-','\u00a0':' ','…':'...'})
def _norm(text):return ' '.join(text.translate(_FOLD).split()).casefold()

def _words(text):
    """[(normalized word, start, end)] for a text; punctuation and quote styles ignored."""
    return [(re.sub(r'[^\w]','',m[0].translate(_FOLD)).casefold(),m.start(),m.end()) for m in re.finditer(r'\S+',text)]

def repair_quote(quote,source):
    """Return the exact source wording for a quote, or None if it is not really there.

    AI models often change quote marks, spacing, dashes or a word or two. Small differences
    are repaired to the teacher's exact source text; invented quotations are still rejected."""
    q=_norm(quote)
    if len(q)<8:return None
    if q in _norm(source):return quote
    from difflib import SequenceMatcher
    qw=[w for w,_,_ in _words(quote) if w];sw=[x for x in _words(source) if x[0]]
    if len(qw)<3 or not sw:return None
    blocks=[b for b in SequenceMatcher(None,qw,[w for w,_,_ in sw],autojunk=False).get_matching_blocks() if b.size]
    if not blocks:return None
    # Use the densest run of matches so scattered common words do not count.
    best=None
    for a in range(len(blocks)):
        for b in range(a,len(blocks)):
            first,last=blocks[a],blocks[b]
            span=last.b+last.size-first.b
            if span>len(qw)*1.4+2:break
            matched=sum(x.size for x in blocks[a:b+1])
            if not best or matched>best[0]:best=(matched,first,last)
    matched,first,last=best
    if matched/len(qw)<0.8:return None
    start=max(0,first.b-first.a);end=min(len(sw)-1,last.b+last.size-1+(len(qw)-last.a-last.size))
    return source[sw[start][1]:sw[end][2]].strip()

def validate_citations(citations,evidence):
    mapping={s['id']:s for s in evidence}
    if not citations:raise ValueError('At least one source citation is required.')
    for c in citations:
        data=c.model_dump() if hasattr(c,'model_dump') else c
        if data['chunk_id'] not in mapping:raise ValueError('Citation falls outside selected material.')
        fixed=repair_quote(data['quote'].strip(),mapping[data['chunk_id']]['text'])
        if fixed is None:raise ValueError('Evidence quotation is not present in the cited source.')
        if fixed!=data['quote']:
            if hasattr(c,'model_dump'):c.quote=fixed
            else:c['quote']=fixed
    return [mapping[c.chunk_id if hasattr(c,'chunk_id') else c['chunk_id']] for c in citations]
