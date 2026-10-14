"""Answer enforcement wrapper for the provided loop; no model/API client."""
import json

from kit.loop.agent import Agent
from agent.guardrails import prepare_answer, scan_for_injected_instructions


class SafeEnvironment:
    """Wrap the trusted executor, never implement tool execution here.

    One wrapper per exchange. The arena still owns interception, gateway
    enforcement, metering and authoritative event recording.
    """
    def __init__(self, executor, ask, gateway=None):
        self.executor = executor
        self.ask = ask
        self.results = []
        self.gateway = gateway

    def execute(self, action):
        if action["kind"] == "answer":
            answer = prepare_answer(action["args"], self.results, self.ask)
            action["args"] = answer
            action["raw"] = "ANSWER " + json.dumps(answer, ensure_ascii=False)
            return self.executor.execute(action)
        result = self.executor.execute(action)
        if self.gateway is not None:
            self.gateway.note_observation(action, result)
        self.results.append(result)
        rows = result.get("rows") or []
        if any(isinstance(row, dict) and
               (row.get("private") is True or scan_for_injected_instructions(str(row.get("body", row.get("definition", "")))).suspicious)
               for row in rows):
            # Prevent the next model turn seeing private/instruction content.
            safe = dict(result)
            safe["rows"] = []
            safe["anchors"] = []
            safe["guardrail_notice"] = "Untrusted/private rows withheld; use another source."
            return safe
        return result


def run_defender(model, executor, *, harness_prompt, team_prompt, task, ask, limits=None, gateway=None):
    """Caller supplies the harness prompt and agent/prompt.md contents.

    Uses the provided model and trusted executor; no keys, network, subprocess
    or world truth lookup. Returns the loop's result with the checked answer.
    """
    env = SafeEnvironment(executor, ask, gateway)
    loop = Agent(model, env, system_prompt=harness_prompt + "\n\n" + team_prompt,
                 task=task, limits=limits)
    return loop.run()
