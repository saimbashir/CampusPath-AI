"""Turn an uploaded file into searchable, source-located excerpts.

Small files are indexed during the upload request. Large books are indexed in a
background thread so free hosting plans (short request timeouts, 512 MB RAM) do not
fail. One background job runs at a time to keep memory use predictable."""
import logging,threading
from sqlalchemy import select
from app.db import SessionLocal
from app.models import Resource,ResourceBlob,Chunk
log=logging.getLogger('campuspath.indexing')
_one_job=threading.BoundedSemaphore(1)


def failure_detail(exc):
    from app.documents.extract import DocumentError
    from sqlalchemy.exc import SQLAlchemyError
    if isinstance(exc,DocumentError):return str(exc)[:300]
    if isinstance(exc,SQLAlchemyError):return 'The database could not save indexed text. Check server logs and retry indexing.'
    if isinstance(exc,ValueError):return str(exc)[:300]
    return f'Indexing failed ({type(exc).__name__}). Check server logs, then retry indexing.'


def index_resource(db,resource,data):
    """Extract text and store chunks for one resource. Returns the number of excerpts."""
    from app.documents.extract import extract_sections
    from app.services.materials import annotated
    parts,outline=extract_sections(resource.filename,data)
    count=0
    for location,text,structure in annotated(parts,resource.filename,outline):
        db.add(Chunk(resource_id=resource.id,location=location[:80],text=text,structure=structure));count+=1
    return count


def semantic_index(db,resource_id):
    from app.ai.vector import enabled,QdrantStore
    if not enabled():return 'Lexical index ready'
    try:
        QdrantStore().index(db.scalars(select(Chunk).where(Chunk.resource_id==resource_id)).all())
        return 'Lexical and semantic indexes ready'
    except Exception:
        return 'Lexical index ready; semantic indexing failed. Administrator can reindex.'


def _background(resource_id):
    with _one_job:
        with SessionLocal() as db:
            resource=db.get(Resource,resource_id);blob=db.get(ResourceBlob,resource_id)
            if not resource or not blob or resource.status!='processing':return
            try:
                count=index_resource(db,resource,blob.data)
                resource.status='ready';resource.status_detail=f'{count} source excerpts indexed.'
                from app.services.notifications import notify_material
                notify_material(db,resource)
                db.commit()
                semantic_index(db,resource_id)
            except Exception as exc:
                db.rollback()
                resource=db.get(Resource,resource_id)
                if resource is None:return
                resource.status='failed'
                resource.status_detail=failure_detail(exc)
                from app.services.notifications import notify_material
                notify_material(db,resource)
                db.commit()
                log.warning('Background indexing failed for resource %s: %s',resource_id,type(exc).__name__)


def start_background(resource_id):
    threading.Thread(target=_background,args=(resource_id,),daemon=True,name=f'index-{resource_id}').start()


def resume_pending():
    """After a restart (free hosts restart often) continue unfinished indexing jobs."""
    try:
        with SessionLocal() as db:
            pending=db.scalars(select(Resource.id).where(Resource.status=='processing')).all()
    except Exception:
        return
    for resource_id in pending:start_background(resource_id)
