"""
This is the job function enqueued onto Redis (via rq) by the API layer.
Run one or more workers with:

    rq worker submissions --url redis://localhost:6379/0

Scaling horizontally = running more worker processes/containers pointed
at the same Redis instance. Each worker picks the next job off the
queue, so submissions are naturally load-balanced across judge hosts.
"""
import datetime as dt
import logging
import time
from functools import wraps

from app.database import SessionLocal
from app import models
from app.judge.executor import executor

logger = logging.getLogger(__name__)

# Retry configuration
MAX_RETRIES = 3
RETRY_DELAY_SECONDS = 2
RETRY_EXCEPTIONS = (ConnectionError, TimeoutError, RuntimeError)


def with_retry(max_retries: int = MAX_RETRIES, delay: float = RETRY_DELAY_SECONDS):
    """Decorator to retry a function on transient failures."""
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            last_exception = None
            for attempt in range(max_retries + 1):
                try:
                    return func(*args, **kwargs)
                except RETRY_EXCEPTIONS as e:
                    last_exception = e
                    if attempt < max_retries:
                        logger.warning("Attempt %d/%d failed: %s. Retrying in %.1fs...",
                                       attempt + 1, max_retries, e, delay)
                        time.sleep(delay)
                    else:
                        logger.error("All %d attempts failed: %s", max_retries + 1, e)
                        raise
            raise last_exception
        return wrapper
    return decorator


def judge_submission_job(submission_id: int):
    db = SessionLocal()
    try:
        submission = db.query(models.Submission).get(submission_id)
        if submission is None:
            logger.warning("Submission %d not found", submission_id)
            return

        logger.info("Judging submission %d for user %d on problem %d",
                    submission_id, submission.user_id, submission.problem_id)

        submission.status = models.SubmissionStatus.RUNNING
        db.commit()

        problem = submission.problem
        test_cases = [
            {"input": tc.input, "expected_output": tc.expected_output}
            for tc in sorted(problem.test_cases, key=lambda t: t.order)
        ]

        verdict = _judge_with_retry(
            submission.language, submission.source_code, test_cases,
            problem.time_limit_sec, problem.memory_limit_mb
        )

        submission.status = models.SubmissionStatus(verdict.status)
        submission.passed_tests = verdict.passed_tests
        submission.total_tests = verdict.total_tests
        submission.runtime_ms = verdict.runtime_ms
        submission.memory_kb = verdict.memory_kb
        submission.stderr = verdict.stderr[:4000] if verdict.stderr else None
        submission.result_detail = verdict.detail
        submission.judged_at = dt.datetime.utcnow()

        # Bump rating on first-ever AC for this user+problem (simple ELO-lite bump)
        # Use atomic check-and-update to avoid race condition
        if verdict.status == "ACCEPTED":
            _bump_rating_on_first_ac(db, submission.user_id, submission.problem_id, problem.difficulty.value)

        db.commit()
        logger.info("Submission %d judged: %s (%d/%d tests, %dms, %dKB)",
                    submission_id, verdict.status, verdict.passed_tests, verdict.total_tests,
                    verdict.runtime_ms, verdict.memory_kb)
    except Exception as e:  # noqa: BLE001 - never let a bad submission kill the worker
        logger.exception("Failed to judge submission %d: %s", submission_id, e)
        db.rollback()
        submission = db.query(models.Submission).get(submission_id)
        if submission:
            submission.status = models.SubmissionStatus.INTERNAL_ERROR
            submission.stderr = str(e)[:2000]
            db.commit()
    finally:
        db.close()


@with_retry(max_retries=MAX_RETRIES, delay=RETRY_DELAY_SECONDS)
def _judge_with_retry(language: str, source_code: str, test_cases: list[dict],
                      time_limit_sec: float, memory_limit_mb: int):
    """Wrapper to add retry logic around executor.judge_submission."""
    return executor.judge_submission(language, source_code, test_cases, time_limit_sec, memory_limit_mb)


def _bump_rating_on_first_ac(db: SessionLocal, user_id: int, problem_id: int, difficulty: str) -> None:
    """
    Atomically bump user rating on first AC for a problem.
    Uses a subquery to check for existing AC submissions in the same transaction.
    """
    # Check if user has any other ACCEPTED submission for this problem
    # Using a subquery with FOR UPDATE to prevent race conditions
    from sqlalchemy import exists, select
    from sqlalchemy.orm import with_for_update

    has_solved = db.query(
        db.query(models.Submission.id).filter(
            models.Submission.user_id == user_id,
            models.Submission.problem_id == problem_id,
            models.Submission.status == models.SubmissionStatus.ACCEPTED,
        ).exists()
    ).scalar()

    if not has_solved:
        bump = {"EASY": 10, "MEDIUM": 25, "HARD": 50}.get(difficulty, 10)
        user = db.query(models.User).filter(models.User.id == user_id).with_for_update().first()
        if user:
            user.rating += bump
            logger.info("Bumped rating for user %d by %d (first AC on problem %d)", user_id, bump, problem_id)

