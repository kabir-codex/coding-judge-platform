import enum
import datetime as dt

from sqlalchemy import (
    Column, Integer, String, Text, DateTime, ForeignKey, Enum, Float, Boolean, JSON, Index
)
from sqlalchemy.orm import relationship

from app.database import Base


class SubmissionStatus(str, enum.Enum):
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    ACCEPTED = "ACCEPTED"
    WRONG_ANSWER = "WRONG_ANSWER"
    TIME_LIMIT_EXCEEDED = "TIME_LIMIT_EXCEEDED"
    MEMORY_LIMIT_EXCEEDED = "MEMORY_LIMIT_EXCEEDED"
    RUNTIME_ERROR = "RUNTIME_ERROR"
    COMPILE_ERROR = "COMPILE_ERROR"
    INTERNAL_ERROR = "INTERNAL_ERROR"


class Difficulty(str, enum.Enum):
    EASY = "EASY"
    MEDIUM = "MEDIUM"
    HARD = "HARD"


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True)
    username = Column(String(32), unique=True, index=True, nullable=False)
    email = Column(String(255), unique=True, index=True, nullable=False)
    hashed_password = Column(String(255), nullable=False)
    is_admin = Column(Boolean, default=False)
    rating = Column(Integer, default=1200)  # ELO-style rating, moves on AC
    created_at = Column(DateTime, default=dt.datetime.utcnow)

    submissions = relationship("Submission", back_populates="user")


class Problem(Base):
    __tablename__ = "problems"

    id = Column(Integer, primary_key=True)
    slug = Column(String(120), unique=True, index=True, nullable=False)
    title = Column(String(200), nullable=False)
    statement = Column(Text, nullable=False)
    difficulty = Column(Enum(Difficulty), default=Difficulty.EASY)
    time_limit_sec = Column(Float, default=2.0)
    memory_limit_mb = Column(Integer, default=256)
    points = Column(Integer, default=100)
    created_at = Column(DateTime, default=dt.datetime.utcnow)

    test_cases = relationship("TestCase", back_populates="problem", cascade="all, delete-orphan")
    submissions = relationship("Submission", back_populates="problem")


class TestCase(Base):
    """
    is_sample=True cases are shown to the user for debugging.
    Hidden cases (is_sample=False) are only used for judging, mirroring
    how real judges prevent hardcoding against visible tests.
    """
    __tablename__ = "test_cases"

    id = Column(Integer, primary_key=True)
    problem_id = Column(Integer, ForeignKey("problems.id"), nullable=False)
    input = Column(Text, nullable=False)
    expected_output = Column(Text, nullable=False)
    is_sample = Column(Boolean, default=False)
    order = Column(Integer, default=0)

    problem = relationship("Problem", back_populates="test_cases")


class Submission(Base):
    __tablename__ = "submissions"
    __table_args__ = (
        Index("ix_submissions_user_problem", "user_id", "problem_id"),
    )

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    problem_id = Column(Integer, ForeignKey("problems.id"), nullable=False)
    language = Column(String(20), nullable=False)
    source_code = Column(Text, nullable=False)
    status = Column(Enum(SubmissionStatus), default=SubmissionStatus.QUEUED)
    runtime_ms = Column(Integer, nullable=True)
    memory_kb = Column(Integer, nullable=True)
    passed_tests = Column(Integer, default=0)
    total_tests = Column(Integer, default=0)
    stderr = Column(Text, nullable=True)
    # Per-test-case breakdown, e.g. [{"case":1,"status":"ACCEPTED","time_ms":12}, ...]
    result_detail = Column(JSON, nullable=True)
    submitted_at = Column(DateTime, default=dt.datetime.utcnow)
    judged_at = Column(DateTime, nullable=True)

    user = relationship("User", back_populates="submissions")
    problem = relationship("Problem", back_populates="submissions")


