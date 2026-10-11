"""MathEngine backend package.

Layers (dependencies point downward only):
  api/        HTTP routes (FastAPI). Thin: validate input, call services, shape output.
  ai/         Ollama client and the allowlisted application-action registry.
  learning/   Exercise service and user progress storage (never stored in the knowledge index).
  knowledge/  Record schema, loader/validator, SQLite index builder, store and retrieval.
  math/       SymPy-based parsing, evaluation and deterministic answer checking.
"""

__version__ = "0.1.0"
