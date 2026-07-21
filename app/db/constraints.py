"""Helpers for building CHECK constraint SQL text safely.

Plain Python string interpolation (f-strings, repr()/str() of tuples) must
never be used to build SQL text: Python's excaping rules are not SQL's, and
it's easy to produce syntax that only happens to work for today's values
(e.g. a bare Python tuple repr for a single-element tuple isn't valid SQl
`IN (...)` syntax, it just happens to render the same way by coincidence).

Instead we build a real SQLAlchemy expression and let the dialect's own
literal-bind compiler render it, so quoting/escaping is handled correctly
regardless of what the values contain.
"""

from sqlalchemy import column
from sqlalchemy.dialects import postgresql


def sql_in_clause(column_name: str, values: tuple[str, ...]) -> str:
    """
    Render `<column_name> IN (...)` as SQL text suitable for a CheckConstraint.

    Values are rendered via SQLAlchemy's literal-bind compilation rather than
    Python's repr()/str(), so single quotes and non-ASCII characters in a value
    are escaped per SQL string-letral rules, and single-element value
    sets render as a correct `IN ('x')` rather than a Python tuple repr.
    """

    clause = column(column_name).in_(values)

    compiled = clause.compile(
        dialect=postgresql.dialect(),
        compile_kwargs={"literal_binds": True},
    )

    return str(compiled)
