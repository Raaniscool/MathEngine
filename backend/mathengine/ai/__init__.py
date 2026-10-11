"""AI layer: local Ollama client and the allowlisted application-action registry.

The model never executes anything itself. It may only *propose* an action name and arguments;
actions.execute_action validates them against a fixed schema before any service is called.
"""
