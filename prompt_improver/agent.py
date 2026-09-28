"""Agent and workflow definitions.

Implementation order:
1. Define one analyzer LlmAgent.
2. Define one evaluator and verify its structured output.
3. Add the remaining evaluator agents.
4. Compose the fan-out/fan-in Workflow.
5. Export the completed workflow as ``root_agent`` for ADK tooling.

The module deliberately contains no runnable agent yet. See README.md for the staged plan.
"""

