"""Isolated business KTV rules; shared execution lives in iteration_engine."""
from .scene import initial_strategy, prompt, improve
from .diversity import plan_batch, DiversityAuditor
from .auditor import MockAuditor, evaluate
