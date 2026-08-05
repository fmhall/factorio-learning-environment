"""Statistical analysis utilities for FLE evaluation results.

Exposes PerformanceAnalyzer / PerformanceMetrics (unbiased pass@k, binomial
confidence intervals, significance tests). Imported lazily because they
depend on pandas/scipy, which are optional extras.
"""

__all__ = [
    "PerformanceAnalyzer",
    "PerformanceMetrics",
]


def __getattr__(name):
    if name in __all__:
        from . import performance_metrics

        return getattr(performance_metrics, name)
    raise AttributeError(f"module '{__name__}' has no attribute '{name}'")
