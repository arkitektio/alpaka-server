def test_stringify_schema():
    """The schema should produce a non-empty SDL string with the root types."""
    from alpaka_server.schema import schema

    sdl = str(schema)

    assert sdl.strip(), "Schema SDL should not be empty"
    assert "type Query" in sdl
    assert "type Mutation" in sdl
    assert "type Subscription" in sdl
