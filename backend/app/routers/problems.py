from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app import models, schemas, auth

router = APIRouter(prefix="/api/problems", tags=["problems"])

DEFAULT_PAGE_SIZE = 20
MAX_PAGE_SIZE = 100


@router.get("", response_model=List[schemas.ProblemSummary])
def list_problems(
    page: int = Query(1, ge=1, description="Page number (1-indexed)"),
    page_size: int = Query(DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE, description="Items per page"),
    db: Session = Depends(get_db),
):
    offset = (page - 1) * page_size
    return db.query(models.Problem).order_by(models.Problem.id).offset(offset).limit(page_size).all()


@router.get("/{slug}", response_model=schemas.ProblemDetail)
def get_problem(slug: str, db: Session = Depends(get_db)):
    problem = db.query(models.Problem).filter(models.Problem.slug == slug).first()
    if not problem:
        raise HTTPException(404, "Problem not found")
    sample_tests = [tc for tc in problem.test_cases if tc.is_sample]
    return schemas.ProblemDetail(
        id=problem.id, slug=problem.slug, title=problem.title, statement=problem.statement,
        difficulty=problem.difficulty.value, time_limit_sec=problem.time_limit_sec,
        memory_limit_mb=problem.memory_limit_mb, points=problem.points,
        sample_tests=sample_tests,
    )


@router.post("", response_model=schemas.ProblemSummary, status_code=201)
def create_problem(
    payload: schemas.ProblemCreate,
    db: Session = Depends(get_db),
    _admin: models.User = Depends(auth.require_admin),
):
    if db.query(models.Problem).filter(models.Problem.slug == payload.slug).first():
        raise HTTPException(400, "Slug already exists")

    # Validate difficulty enum
    try:
        difficulty = models.Difficulty(payload.difficulty.upper())
    except ValueError:
        raise HTTPException(400, f"Invalid difficulty: {payload.difficulty}. Must be one of: EASY, MEDIUM, HARD")

    problem = models.Problem(
        slug=payload.slug, title=payload.title, statement=payload.statement,
        difficulty=difficulty,
        time_limit_sec=payload.time_limit_sec, memory_limit_mb=payload.memory_limit_mb,
        points=payload.points,
    )
    for i, tc in enumerate(payload.test_cases):
        problem.test_cases.append(models.TestCase(
            input=tc.input, expected_output=tc.expected_output,
            is_sample=tc.is_sample, order=i,
        ))
    db.add(problem)
    db.commit()
    db.refresh(problem)
    return problem

