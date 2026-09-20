"""Smoke test: the GraphQL schema must build and render to a non-empty SDL string.

No database required — this only imports and stringifies the schema.
"""

from alpaka_server.schema import schema


def test_print_schema():
    sdl = str(schema)
    print(sdl)  # visible with `pytest -s`
    assert sdl.strip(), "Schema SDL should not be empty"


def test_embedding_columns_stay_out_of_the_schema():
    """The vector columns are storage, not API: no type or input may expose them.

    The word "embedding" itself is legitimately in this schema (the LLM feature and usage
    enums), so the check is for the two column names.
    """
    from alpaka_server.schema import schema

    sdl = str(schema)
    assert "embeddingModel" not in sdl
    assert not any(line.strip().startswith("embedding:") for line in sdl.splitlines())
