from typing import List

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from redis import Redis
from rq import Queue

from app.database import get_db
from app.config import settings
from app import models, schemas, auth
from app.judge.worker import judge_submission_job
from app.judge.languages import LANGUAGE_CONFIG

router = APIRouter(prefix="/api/submissions", tags=["submissions"])

_redis_conn = Redis.from_url(settings.REDIS_URL)
_queue = Queue(settings.SUBMISSION_QUEUE, connection=_redis_conn)


@router.post("", response_model=schemas.SubmissionOut, status_code=201)
def submit_code(
    payload: schemas.SubmissionCreate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_user),
):
    if payload.language not in LANGUAGE_CONFIG:
        raise HTTPException(400, f"Unsupported language '{payload.language}'")

    problem = db.query(models.Problem).get(payload.problem_id)
    if not problem:
        raise HTTPException(404, "Problem not found")

    if len(payload.source_code.encode()) > 64_000:
        raise HTTPException(400, "Source code too large (64KB limit)")

    submission = models.Submission(
        user_id=current_user.id,
        problem_id=problem.id,
        language=payload.language,
        source_code=payload.source_code,
        status=models.SubmissionStatus.QUEUED,
        total_tests=len(problem.test_cases),
    )
    db.add(submission)
    db.commit()
    db.refresh(submission)

    # Hand off to the worker pool via Redis; this call returns immediately.
    _queue.enqueue(judge_submission_job, submission.id, job_timeout=settings.JOB_TIMEOUT)

    return submission


@router.get("/{submission_id}", response_model=schemas.SubmissionOut)
def get_submission(
    submission_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_user),
):
    submission = db.query(models.Submission).get(submission_id)
    if not submission:
        raise HTTPException(404, "Submission not found")
    if submission.user_id != current_user.id and not current_user.is_admin:
        raise HTTPException(403, "Not your submission")
    return submission


@router.get("", response_model=List[schemas.SubmissionOut])
def list_my_submissions(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_user),
):
    return (
        db.query(models.Submission)
        .filter(models.Submission.user_id == current_user.id)
        .order_by(models.Submission.id.desc())
        .limit(50)
        .all()
    )

