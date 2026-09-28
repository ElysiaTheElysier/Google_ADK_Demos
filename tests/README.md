# Planned tests

Start with deterministic tests for the Pydantic schemas:

- required fields;
- score boundaries from 1 to 5;
- serialization of each output contract.

Do not begin by mocking the entire ADK runtime. Add workflow integration tests only after the
single-agent path works end to end.

