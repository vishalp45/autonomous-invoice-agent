# Hints for agent/loop.py

The provider layer (agent/llm.py) hides each model's message format. You only use:

    llm.add_user(task)                      # start the conversation
    turn = llm.generate()                   # model decides: turn.text, turn.tool_calls
    llm.add_tool_results([(call, result)])  # feed results back

Each call has .name and .args.  toolbox.run(call.name, call.args) returns a dict.
Model finished  <=>  turn.tool_calls is empty.
The history (the agent's memory) lives inside `llm`.
