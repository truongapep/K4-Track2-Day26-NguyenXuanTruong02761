"""agent/gateway.py — YOUR control plane. CONTRACTS.md section 4, exactly.

READ agent/README.md FIRST — it maps all five files in this directory to what
each is scored on. This file is the one CONTRACTS.md calls "the trusted
envelope's untrusted half": every single MCP / A2A / DISCOVER command your
agent's model wants to make passes through `Gateway.decide` before it is
allowed to happen.

WHY THERE IS NO `execute()` METHOD ON `GatewayContext` (read this before you
go looking for one — there isn't one, and that is not an oversight)
----------------------------------------------------------------------------
CONTRACTS.md section 4's trusted envelope, reproduced here because it is the
one diagram worth memorising:

    [ trusted ]   loop emits a raw action line
         v
    [ trusted ]   INTERCEPT + CANONICALISE -> Command        (kit/loop/agent.py)
         v
    [ UNTRUSTED ] Gateway.decide(cmd) -> Decision             <- THIS FILE
         v
    [ trusted ]   ENFORCE: honour the Decision, meter it,
                  apply the active mutation, execute the
                  ToolCall or refuse it                       (the arena)
         v
    [ trusted ]   RECORD the authoritative L1 event, then
                  RENDER the Observation                      (the arena)
         v
    [ trusted ]   the model sees the Observation

`decide()` returns a *decision*, never a *result*. You cannot reach a tool
server, a file, a socket, or a clock from in here — there is nothing to
call. Two things follow from that, and both matter more than they look:

  1. YOUR TRACE CANNOT BE FORGED. Every `command` / `decision` / `enforced`
     / `tool_call` / `tool_result` L1 event (CONTRACTS.md 5.2) is written by
     the arena, from what the arena itself actually did — never from
     anything you claimed happened. A student gateway that wanted to lie
     about having blocked an attack ("I totally denied that, trust me")
     simply has no channel to lie through: the only thing you ever hand
     back is this one small `Decision` value, and the arena is the one that
     turns it into history.
  2. NOBODY CAN ACCUSE YOU OF A CALL YOU DID NOT AUTHORISE, either. Because
     `decide()` is the ONLY door a command can walk through on its way to
     actually running, a prosecutor's `enforcement_failure` claim against
     you has exactly one thing to point at: the `Decision` you returned for
     that specific `cmd_id`. There is no ambiguity about "maybe the loop
     called the tool directly" — CONTRACTS.md 4.2 removed that path on
     purpose, and kit/loop/agent.py's own module docstring names the same
     invariant from the other side (the loop never imports this module,
     never sees a `Decision`, never executes anything itself).

The cost of that guarantee is that this file is PURE: synchronous, no I/O,
no threads, no `sleep`, 250 ms wall-clock deadline (RULES.md section 3).
Raising anything, returning something that is not a valid `Decision`, or
missing the deadline is treated by the arena as a DENIED command PLUS a 2
credit penalty PLUS an `integrity` event that hands the prosecutor a free
`enforcement_failure` — CONTRACTS.md 4.1's charging table, reproduced in
agent/README.md's own table. Getting this file to just plainly return valid
`Decision` values, every time, is worth more than getting it clever.

THE STARTER'S SHAPE (read this before you start editing `decide()`)
----------------------------------------------------------------------------
The original starter forwarded every command. This single-member team submission
now implements ROUTE, ADMIT, AUTHORIZE and BUDGET in decide(). See TEAM_REPORT.md
for completed checks and remaining limits. Provenance and peer admission
must come from trusted arena callbacks. Structured delegation tokens, when
supplied, use the kit verifier; ANSWER enforcement is in agent.defender.

ONE THING WORTH INTERNALISING BEFORE YOU WRITE YOUR FIRST REAL CHECK:
`verdict="deny"` costs the CALLER (your own team) **zero credits** —
CONTRACTS.md 4.1's charging table has exactly one $0 row, and it is this
one. Refusing to make a call you cannot justify is FREE. That makes
abstention a real strategy, not a luxury you can't afford: a `deny` you can
defend beats a `forward` you can't, every time a prosecutor is watching.

Stdlib only. No network, no randomness, no wall-clock reads, no sleeping —
none of that would even survive the kernel sandbox (CONTRACTS.md 12), but
the point is this file has no reason to want any of it in the first place.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any, Mapping, Protocol, runtime_checkable

# kit.mcp.types is a collaborator's file (workspace hard rule 2: import it,
# degrade gracefully). It is present as of this writing and is core, stable
# infrastructure (CONTRACTS.md 3.1) — but this module must still not fail to
# IMPORT if a concurrent edit ever breaks it transiently. When it is
# unavailable, `Decision.call` type-checking is skipped (not enforced), and
# `Gateway.decide` falls back to a minimal local dict-shaped stand-in so the
# rest of this file — everything that does not need a *real* ToolCall — still
# runs.
try:
    from kit.mcp.types import ToolCall
    _TOOLCALL_AVAILABLE = True
except ImportError:  # pragma: no cover - collaborator file
    ToolCall = Any  # type: ignore[assignment, misc]
    _TOOLCALL_AVAILABLE = False

# kit.loop.agent is also a collaborator's file, used only by this module's
# own __main__ demo (to build real Commands the same way the arena's trusted
# canonicaliser would) — never by decide() itself, which never touches the
# loop. Degraded the same way.
try:
    from kit.loop.agent import canonicalise_action as _canonicalise_action
except ImportError:  # pragma: no cover - collaborator file
    _canonicalise_action = None

from agent.telemetry import RecordingGatewayContext, Telemetry
from agent.strategy import cheap_mask, is_catalog_trap, successor_of
from kit.mcp.specs import TOOL_SPECS, A2A_PEERS, cost
from kit.mcp.a2a import verify_card, verify_delegation
from agent.guardrails import scan_for_injected_instructions

__all__ = [
    "COMMAND_KINDS",
    "DECISION_VERDICTS",
    "Command",
    "Decision",
    "GatewayContext",
    "Gateway",
]

# CONTRACTS.md 4.1: `Command.kind` — "mcp" | "a2a" | "discover". An "answer"
# action is NEVER a Command (kit/loop/agent.py's own module docstring: "an
# answer is not a tool call routed to a server, so it never becomes a
# Command at all") — it is handled entirely by the loop/arena and never
# reaches `Gateway.decide`.
COMMAND_KINDS: frozenset[str] = frozenset({"mcp", "a2a", "discover"})

# CONTRACTS.md 4.1: `Decision.verdict` — the closed three-member set.
DECISION_VERDICTS: frozenset[str] = frozenset({"forward", "deny", "rewrite"})


@dataclass(frozen=True, slots=True)
class Command:
    """CONTRACTS.md 4.1, field for field — "canonicalised by the arena
    BEFORE the student sees it". You never build one of these from your own
    agent's raw text; the arena's canonicaliser (kit/loop/agent.py's
    `canonicalise_action`, run inside the trusted envelope) already did that
    work and minted `cmd_id` by the time `decide()` sees it. The
    `from_action_dict` classmethod below exists only so this file's own demo
    (and your local tests, if you write any) can build a realistic `Command`
    without duplicating the arena's canonicalisation logic."""

    cmd_id: str
    kind: str  # "mcp" | "a2a" | "discover" — see COMMAND_KINDS
    raw: str
    server: str
    tool: str
    args: dict
    fields: tuple[str, ...]
    headers: dict
    lease_id: str | None
    call_index: int

    def __post_init__(self) -> None:
        if not isinstance(self.cmd_id, str) or not self.cmd_id:
            raise ValueError(f"Command.cmd_id must be a non-empty str, got {self.cmd_id!r}")
        if self.kind not in COMMAND_KINDS:
            raise ValueError(f"Command.kind must be one of {sorted(COMMAND_KINDS)}, got {self.kind!r}")
        if not isinstance(self.server, str) or not self.server:
            raise ValueError(f"Command.server must be a non-empty str, got {self.server!r}")
        if not isinstance(self.tool, str) or not self.tool:
            raise ValueError(f"Command.tool must be a non-empty str, got {self.tool!r}")
        if not isinstance(self.args, dict):
            raise ValueError(f"Command.args must be a dict, got {type(self.args).__name__}")
        if not isinstance(self.headers, dict):
            raise ValueError(f"Command.headers must be a dict, got {type(self.headers).__name__}")
        if (
            not isinstance(self.call_index, int)
            or isinstance(self.call_index, bool)
            or self.call_index < 0
        ):
            raise ValueError(f"Command.call_index must be a non-negative int, got {self.call_index!r}")

    @classmethod
    def from_action_dict(cls, action: Mapping[str, Any], *, cmd_id: str) -> "Command":
        """Build a `Command` from the dict shape `kit.loop.agent.canonicalise_action`
        returns (`kind, raw, server, tool, args, fields, headers, lease_id,
        call_index` — everything except the arena-minted `cmd_id`, supplied
        here as a keyword). Raises `ValueError` if `action["kind"] ==
        "answer"` — an answer is never a Command (see the module docstring).
        This is a convenience for tests/demos, not something the real arena
        calls: the trusted envelope mints `cmd_id` itself and constructs the
        real `Command` on its own side of the boundary."""
        kind = action.get("kind")
        if kind == "answer":
            raise ValueError(
                "an 'answer' action never becomes a Command (kit/loop/agent.py: "
                "\"an answer is not a tool call routed to a server\") — do not "
                "route it through Gateway.decide at all"
            )
        return cls(
            cmd_id=cmd_id,
            kind=kind,
            raw=action["raw"],
            server=action["server"],
            tool=action["tool"],
            args=dict(action.get("args", {})),
            fields=tuple(action.get("fields", ())),
            headers=dict(action.get("headers", {})),
            lease_id=action.get("lease_id"),
            call_index=action.get("call_index", 0),
        )

    def to_dict(self) -> dict:
        return {
            "cmd_id": self.cmd_id,
            "kind": self.kind,
            "raw": self.raw,
            "server": self.server,
            "tool": self.tool,
            "args": dict(self.args),
            "fields": list(self.fields),
            "headers": dict(self.headers),
            "lease_id": self.lease_id,
            "call_index": self.call_index,
        }


@dataclass(frozen=True, slots=True)
class Decision:
    """CONTRACTS.md 4.1, field for field.

    Validated strictly (`__post_init__`) because a *structurally* invalid
    `Decision` is charged exactly like a raised exception — CONTRACTS.md
    4.1's charging table: "malformed Decision (schema-invalid) -> 2 cr
    penalty, command denied." Failing loudly HERE, in your own process
    during development, is strictly better than discovering it live in a
    duel as an unexplained penalty.

    `verdict == "deny"` requires a non-empty `reason` (CONTRACTS.md 4.1:
    "required when verdict == 'deny'; shown in the combat log") and
    forbids `call` — a real denial has nothing left to carry out.
    `verdict` in `("forward", "rewrite")` requires `call` to be set — the
    arena executes exactly that `ToolCall`, nothing else, per the trusted
    envelope's whole point (see the module docstring)."""

    verdict: str  # "forward" | "deny" | "rewrite" — see DECISION_VERDICTS
    reason: str | None = None
    call: "ToolCall | None" = None
    quarantine: bool = False
    note: str | None = None

    def __post_init__(self) -> None:
        if self.verdict not in DECISION_VERDICTS:
            raise ValueError(
                f"Decision.verdict must be one of {sorted(DECISION_VERDICTS)}, got {self.verdict!r}"
            )
        if self.verdict == "deny":
            if not isinstance(self.reason, str) or not self.reason.strip():
                raise ValueError("Decision.verdict=='deny' requires a non-empty 'reason'")
            if self.call is not None:
                raise ValueError("Decision.verdict=='deny' must not carry a 'call' — there is nothing to run")
        else:  # forward | rewrite
            if self.call is None:
                raise ValueError(f"Decision.verdict=={self.verdict!r} requires 'call' to be set")
            if _TOOLCALL_AVAILABLE and not isinstance(self.call, ToolCall):
                raise ValueError(
                    f"Decision.call must be a kit.mcp.types.ToolCall instance, got {type(self.call).__name__}"
                )
        if not isinstance(self.quarantine, bool):
            raise ValueError(f"Decision.quarantine must be a bool, got {self.quarantine!r}")
        if self.note is not None and not isinstance(self.note, str):
            raise ValueError(f"Decision.note must be a str or None, got {self.note!r}")

    def to_dict(self) -> dict:
        return {
            "verdict": self.verdict,
            "reason": self.reason,
            "call": self.call.to_dict() if self.call is not None and hasattr(self.call, "to_dict") else self.call,
            "quarantine": self.quarantine,
            "note": self.note,
        }


@runtime_checkable
class GatewayContext(Protocol):
    """CONTRACTS.md 4.2 — "read-only, arena-provided". Note what this is
    NOT: unlike `Command`/`Decision` above, CONTRACTS.md writes this as a
    plain `class`, not a `@dataclass(frozen=True, ...)`. That is a real
    signal, not an inconsistency — a `GatewayContext` is a LIVE VIEW the
    arena owns and updates as the duel actually progresses (credits get
    spent, rounds advance, leases mint and expire), not a frozen snapshot
    you receive once. This file therefore models it as a structural
    `Protocol`: the arena hands your `Gateway.__init__` some object shaped
    like this (see `agent/telemetry.py`'s `RecordingGatewayContext` for a
    concrete example your own tests/demos can build), and you read
    `self.ctx.<field>` fresh every time `decide()` runs — NEVER cache a
    context field into a local variable across calls; if you need memory
    that persists across the duel (a cache, a budget tracker, drift notes),
    keep it on YOUR OWN `Gateway` instance attributes instead (CONTRACTS.md
    4.3: "Gateway is instantiated once per duel... persists across the 10
    rounds").

    There is deliberately no `execute` method here — see the module
    docstring's "WHY THERE IS NO execute() METHOD" section. `emit` is the
    ONE thing you can do that has any side effect at all, and it writes to
    `own_telemetry` only: your own side, never scored, never shown to the
    opponent (`agent/telemetry.py` wraps it)."""

    act: str  # "learner:sv-0417" — WHOM YOU SERVE. Authority derives from this.
    sub: str  # "agent:vlearn-tutor" — what you are. NOT authority.
    scopes: frozenset[str]  # {"wiki.read"}; writes need "wiki.write:progress" etc.
    credits: int  # remaining this duel
    round: int
    call_index: int
    leases: tuple[str, ...]  # live lease ids, arena-tracked
    history: tuple[Mapping[str, Any], ...]  # YOUR OWN prior (Command, Decision, outcome) triples this duel

    def emit(self, name: str, **payload: Any) -> None: ...


class Gateway:
    """The control plane. One instance per duel (CONTRACTS.md 4.3) — built
    once at duel start with a `GatewayContext`, then asked to `decide()` on
    every MCP/A2A/DISCOVER command either side of the duel makes for all 10
    rounds. See the module docstring for the trusted-envelope diagram and
    why there is no `execute()` to call instead.

    Single-member team memory tracks trusted provenance, admitted peers, authorised
    write keys, rate windows and estimated spend. ctx remains the arena's
    live authority for identities, scopes, credits and valid leases.
    """

    def __init__(self, ctx: GatewayContext) -> None:
        self.ctx = ctx
        self._telemetry = Telemetry(ctx)

        # --- per-duel memory, unused by the naive starter below ---------
        # A cache of anchor -> body-ish data you have already paid for this
        # duel (agent/strategy.py's ResultCache is a ready-made version of
        # this). Populating it needs the *result* of a call, which decide()
        # never sees (it only sees the outgoing Command) — you would fill
        # this from whatever the arena hands back to your agent loop AFTER
        # a call executes, then consult it here on the NEXT decide() call
        # for the same anchor.
        self._seen_anchors: dict[str, Any] = {}
        # Credits this team has authorised so far this duel — its
        # own running total, independent of (and a cross-check against)
        # `ctx.credits`, which the arena maintains authoritatively.
        self._credits_authorised: int = 0
        # Command ids you have already denied, in case a later job wants to
        # know "have I already said no to this once".
        self._denied_cmd_ids: set[str] = set()
        self._write_keys: set[str] = set()
        self._admitted_cards: dict[str, dict] = {}
        self._provenance: dict[str, tuple[str, str | None]] = {}
        self._rate_calls: dict[tuple[str, str], list[int]] = {}
        self._budget_round = None
        self._round_authorised = 0
        self._seen_tokens: set[str] = set()

    def decide(self, cmd: Command) -> Decision:
        """Pure control-plane policy: ROUTE, ADMIT, AUTHORIZE, BUDGET.

        Only ctx.emit writes telemetry. No world/file/network/clock access.
        Result callbacks accept trusted arena observations, not model assertions.
        """
        self._telemetry.decision_seen(cmd)
        headers = {}
        for key, value in cmd.headers.items():
            if not isinstance(key, str):
                return self.deny(cmd, "header name must be a string")
            name = key.lower()
            if name in headers and headers[name] != value:
                return self.deny(cmd, "conflicting header values")
            headers[name] = value

        # ROUTE: only headers can request a route. Never infer freshness from
        # 'c' versus 'w'; retain an explicit route unless observed provenance
        # supplies the fresher replica for this exact anchor.
        if any(key in cmd.args for key in ("route", "_route", "replica")):
            return self.deny(cmd, "routing metadata must be in headers, not arguments")
        server, tool = successor_of(cmd.server, cmd.tool) or (cmd.server, cmd.tool)
        spec = TOOL_SPECS.get((server, tool))
        if spec is None:
            return self.deny(cmd, "unknown server/tool")
        is_peer = server in A2A_PEERS
        if (cmd.kind == "a2a") != is_peer:
            return self.deny(cmd, "command kind does not match server type")
        if headers.get("x-server-fingerprint") == "unvouched":
            return self.deny(cmd, "server fingerprint is not vouched for")
        if headers.get("x-card-signature") == "invalid":
            return self.deny(cmd, "peer card signature is invalid")
        args = dict(cmd.args)
        for key in ("note", "instruction", "peer_response"):
            if isinstance(args.get(key), str) and scan_for_injected_instructions(args[key]).suspicious:
                return self.deny(cmd, "untrusted content requests an instruction override")
        if not is_peer:
            replica = headers.get("mcp-replica", "w")
            known = self._provenance.get(str(args.get("anchor", "")))
            if known and known[1] in ("w", "c"):
                replica = known[1]
            if replica not in ("w", "c"):
                return self.deny(cmd, "invalid replica header")
            headers["mcp-replica"] = replica

        # ADMIT: leases are the arena's live state, never an invented token.
        if spec.needs_lease and (not cmd.lease_id or cmd.lease_id not in self.ctx.leases):
            return self.deny(cmd, "get_frame requires a live arena lease")
        if is_peer:
            card = self._admitted_cards.get(server)
            if not card or card.get("verified") is not True or tool not in card.get("skills", ()):
                return self.deny(cmd, "peer/skill not admitted by trusted registry")
            if headers.get("aud") not in (server, "a2a:" + server, "mcp:" + server):
                return self.deny(cmd, "delegation audience does not match peer")
            token = headers.get("delegation-token")
            if token is not None:
                if not isinstance(token, Mapping):
                    return self.deny(cmd, "delegation token must have the kit's structured shape")
                admission = verify_delegation(token, aud="a2a:" + server, call_index=cmd.call_index,
                                              expected_act=self.ctx.act, seen_token_ids=self._seen_tokens)
                if not admission.admitted:
                    return self.deny(cmd, "delegation token verification failed")
        if spec.is_write:
            if any(not isinstance(headers.get(key), str) or not headers[key].strip()
                   for key in spec.required_headers):
                return self.deny(cmd, "write requires If-Match and Idempotency-Key")
            target = str(args.get("learner") if server == "progress" else args.get("anchor", ""))
            pinned = self._provenance.get(target)
            if pinned is None or headers["if-match"] != pinned[0]:
                return self.deny(cmd, "write requires matching observed provenance etag")
            if headers["idempotency-key"] in self._write_keys:
                return self.deny(cmd, "write key already authorised this duel")

        # AUTHORIZE: sub describes the agent; act defines the learner served.
        required_scope = "wiki.write:" + server if spec.is_write else "wiki.read"
        if required_scope not in self.ctx.scopes:
            return self.deny(cmd, "required scope not granted by arena context")
        for key in ("learner", "learner_id"):
            if key in args and self._learner_identity(args[key]) != self._learner_identity(self.ctx.act):
                return self.deny(cmd, "target learner differs from ctx.act")
        if "act" in headers and self._learner_identity(headers["act"]) != self._learner_identity(self.ctx.act):
            return self.deny(cmd, "delegation act differs from ctx.act")
        if server in ("progress", "roster") and not args.get("learner"):
            return self.deny(cmd, "learner target is required")

        # BUDGET: preserve explicitly requested evidence fields. Narrow only
        # catalogue dumps; dropping body from an answer fetch would fabricate
        # grounding. Query limit caps the row-dependent cost before execution.
        fields = tuple(cmd.fields)
        if (cmd.server, cmd.tool) == ("slides", "search"):
            # query returns anchors in its envelope, not an 'anchor' row
            # field; search.snippet becomes query.body. Preserve that meaning
            # instead of forwarding a mask invalid for the successor tool.
            if fields != ("*",):
                fields = tuple(sorted({"body" if f == "snippet" else f
                                       for f in (fields or ("anchor", "title")) if f != "anchor"}))
                if not fields:
                    fields = ("title",)
        if is_catalog_trap(server, tool, fields):
            fields = cheap_mask(server, tool, ("name",) if server == "registry" else ("term",))
        effective = spec.all_fields if fields == ("*",) else (fields or spec.default_fields)
        if any(field not in spec.all_fields for field in effective):
            return self.deny(cmd, "field mask contains an unknown field")
        rows = 1
        if spec.row_weight:
            rows = args.get("limit", 5)
            if not isinstance(rows, int) or isinstance(rows, bool) or rows < 1:
                return self.deny(cmd, "query limit must be a positive integer")
            rows = min(rows, 5)
            args["limit"] = rows
        estimated = cost(server, tool, fields=fields, n_rows=rows)
        round_no = self.ctx.round
        if self._budget_round != round_no:
            self._budget_round, self._round_authorised = round_no, 0
        reserve = max(0, 10 - max(1, round_no)) * 8
        if estimated > self.ctx.credits or self.ctx.credits - estimated < reserve:
            return self.deny(cmd, "call would consume credits reserved for remaining rounds")
        if self._round_authorised + estimated > 12:
            return self.deny(cmd, "round authorisation allowance exhausted")
        if spec.rate_limit:
            allowed, window = spec.rate_limit
            recent = [r for r in self._rate_calls.get((server, tool), []) if r > round_no - window]
            if len(recent) >= allowed:
                return self.deny(cmd, "tool rate window exhausted")
            self._rate_calls[(server, tool)] = recent + [round_no]

        routed = replace(cmd, server=server, tool=tool, args=args, fields=fields, headers=headers)
        call = self._to_tool_call(routed)
        self._round_authorised += estimated
        self._credits_authorised += estimated
        if spec.is_write:
            self._write_keys.add(headers["idempotency-key"])
        if is_peer and isinstance(headers.get("delegation-token"), Mapping):
            self._seen_tokens.add(headers["delegation-token"]["token_id"])
        decision = Decision(verdict="rewrite" if routed != cmd else "forward", call=call,
                            note=f"estimated cost <= {estimated}; reserve={reserve}")
        self._telemetry.decision_made(cmd, decision)
        return decision

    @staticmethod
    def _learner_identity(value) -> str | None:
        if not isinstance(value, str) or ":" not in value:
            return None
        namespace, identifier = value.split(":", 1)
        if namespace.lower() != "learner" or not identifier:
            return None
        return "learner:" + identifier

    def note_card(self, server: str, card: Mapping) -> None:
        """Trusted registry callback only; never call with a model's assertion.

        'verified' represents the arena's verification outcome. This gateway
        does not claim to verify a raw Agent Card or signed JWT itself.
        """
        skills = card.get("skills", ())
        verified = card.get("verified") is True
        if "signature" in card:
            admission = verify_card(card)
            verified = admission.admitted and card.get("name") == server
        if server in A2A_PEERS and verified and isinstance(skills, (list, tuple)):
            self._admitted_cards[server] = {"verified": True, "skills": tuple(skills)}
        else:
            self._admitted_cards.pop(server, None)

    def note_result(self, anchor: str, etag: str, fresher: str | None = None) -> None:
        """Trusted provenance callback; no I/O and no inferred freshness."""
        if isinstance(anchor, str) and isinstance(etag, str) and etag:
            self._provenance[anchor] = (etag, fresher if fresher in ("w", "c") else None)

    def note_observation(self, action: Mapping, result: Mapping) -> None:
        """Consume a trusted registry provenance result, never a model claim."""
        if result.get("ok") is not True or (action.get("server"), action.get("tool")) != ("registry", "provenance"):
            return
        anchor = (action.get("args") or {}).get("anchor")
        etag = result.get("etag")
        fresher = None
        for row in result.get("rows") or ():
            if isinstance(row, Mapping):
                etag = row.get("etag", etag)
                fresher = row.get("fresher", fresher)
        self.note_result(anchor, etag, fresher)

    def deny(self, cmd: Command, reason: str) -> Decision:
        """Return a free refusal with a reason and record single-member team telemetry."""
        self._denied_cmd_ids.add(cmd.cmd_id)
        decision = Decision(verdict="deny", reason=reason)
        self._telemetry.decision_made(cmd, decision)
        return decision

    def _to_tool_call(self, cmd: Command) -> "ToolCall":
        """`Command` -> the `ToolCall` (CONTRACTS.md 3.1) the arena will
        actually execute on a `forward`/`rewrite` verdict. When
        `kit.mcp.types` is unavailable (see the module-level import guard),
        falls back to a plain dict carrying the identical fields — `Decision`
        accepts it either way (the `ToolCall` isinstance check inside
        `Decision.__post_init__` only runs when the real class loaded)."""
        fields = {
            "server": cmd.server,
            "tool": cmd.tool,
            "args": dict(cmd.args),
            "fields": cmd.fields,
            "headers": dict(cmd.headers),
            "lease_id": cmd.lease_id,
            "call_index": cmd.call_index,
        }
        if _TOOLCALL_AVAILABLE:
            return ToolCall(**fields)
        return fields  # type: ignore[return-value]


if __name__ == "__main__":
    print("=== agent.gateway: Command / Decision validation ===\n")

    good_cmd = Command(
        cmd_id="cmd:0000",
        kind="mcp",
        raw="MCP slides.get_frame anchor=Frame:3f2a9c11/w/041 fields=title,body lease=lse_7f21",
        server="slides",
        tool="get_frame",
        args={"anchor": "Frame:3f2a9c11/w/041"},
        fields=("body", "title"),
        headers={},
        lease_id="lse_7f21",
        call_index=0,
    )
    print(f"  Command constructed: {good_cmd}")
    assert good_cmd.kind == "mcp"

    print("\n  Rejection demo (each must raise ValueError):")

    def _expect_value_error(label: str, fn) -> None:
        try:
            fn()
        except ValueError as exc:
            print(f"    [{label:38}] -> ValueError: {exc}")
        else:
            raise AssertionError(f"expected ValueError for case {label!r}")

    _expect_value_error("Command.kind == 'answer'", lambda: Command(
        cmd_id="cmd:0001", kind="answer", raw="x", server="slides", tool="get_frame",
        args={}, fields=(), headers={}, lease_id=None, call_index=0,
    ))
    _expect_value_error("Decision verdict='deny' with no reason", lambda: Decision(verdict="deny"))
    _expect_value_error(
        "Decision verdict='forward' with no call", lambda: Decision(verdict="forward")
    )
    _expect_value_error(
        "Decision verdict='deny' carrying a call",
        lambda: Decision(verdict="deny", reason="nope", call={"server": "x", "tool": "y"}),
    )
    _expect_value_error("Decision verdict='?' unknown", lambda: Decision(verdict="???"))

    print("\n=== Command.from_action_dict — real canonicaliser integration ===\n")
    if _canonicalise_action is None:
        print("  kit.loop.agent not importable yet — skipping the live canonicaliser demo")
        demo_commands: list[Command] = [good_cmd]
    else:
        raw_actions = [
            "MCP registry.provenance anchor=Frame:3f2a9c11/w/041 fields=etag",
            'MCP slides.query q="streamable http replaces http+sse" fields=title,body',
            "A2A curriculum-analyst.which_days_cover concept=Concept:streamable-http fields=anchor,course_day,track",
            "DISCOVER registry.list_servers fields=name",
        ]
        demo_commands = []
        for i, raw in enumerate(raw_actions):
            action = _canonicalise_action(raw, call_index=i)
            cmd = Command.from_action_dict(action, cmd_id=f"cmd:{i:04d}")
            print(f"  {raw!r}\n    -> {cmd.kind}: {cmd.server}.{cmd.tool} fields={cmd.fields}")
            demo_commands.append(cmd)
        assert {c.kind for c in demo_commands} == {"mcp", "a2a", "discover"}

        answer_action = _canonicalise_action(
            'ANSWER {"text": "day 26, track P2T2"}', call_index=None
        )
        try:
            Command.from_action_dict(answer_action, cmd_id="cmd:9999")
        except ValueError as exc:
            print(f"\n  an 'answer' action correctly refuses to become a Command: {exc}")
        else:
            raise AssertionError("expected ValueError for an 'answer' action")

    print("\n=== Gateway.decide — the naive starter forwards everything ===\n")
    ctx = RecordingGatewayContext(
        act="learner:sv-0401",
        sub="agent:one-person-demo",
        scopes=frozenset({"wiki.read"}),
        credits=100,
        round=1,
        call_index=0,
        leases=(),
        history=(),
    )
    assert isinstance(ctx, GatewayContext), "RecordingGatewayContext must structurally satisfy GatewayContext"
    gw = Gateway(ctx)
    ctx.leases = ("lse_7f21",)
    gw.note_card("curriculum-analyst", {"verified": True, "skills": ["which_days_cover"]})
    for cmd in demo_commands:
        ctx.round += 1
        if cmd.kind == "a2a":
            cmd = replace(cmd, headers={"aud": cmd.server})
        decision = gw.decide(cmd)
        print(f"  decide({cmd.server}.{cmd.tool}) -> verdict={decision.verdict!r} quarantine={decision.quarantine}")
        assert decision.verdict in ("forward", "rewrite", "deny")
        assert decision.call is not None
        call_dict = decision.call.to_dict() if hasattr(decision.call, "to_dict") else decision.call
        assert call_dict["server"] == cmd.server
        assert call_dict["tool"] == cmd.tool
        assert tuple(call_dict["fields"]) == tuple(cmd.fields)

    print(f"\n=== Gateway.deny — the unused-by-default free-abstention path ===\n")
    denial = gw.deny(demo_commands[0], reason="demo: withholding pending a fresher registry.provenance read")
    print(f"  gw.deny(...) -> verdict={denial.verdict!r} reason={denial.reason!r} call={denial.call!r}")
    assert denial.verdict == "deny"
    assert denial.call is None
    assert demo_commands[0].cmd_id in gw._denied_cmd_ids

    print(f"\n=== own_telemetry — recorded on YOUR side only, never shown to the opponent ===\n")
    print(f"  {len(ctx.events)} events recorded on this ctx this run:")
    for ev in ctx.events:
        print(f"    {ev['name']}: {sorted(ev['payload'].keys())}")
    assert len(ctx.events) >= len(demo_commands) * 2 + 1  # decision_seen + decision_made per call, plus the deny

    print("\nAll agent/gateway.py demos passed.")
