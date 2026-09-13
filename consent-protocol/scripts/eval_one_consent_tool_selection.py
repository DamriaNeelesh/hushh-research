#!/usr/bin/env python3
"""Measure which tool One reaches for first on ordinary consent questions.

Usage:
    GENAI_GOOGLE_CLOUD_PROJECT=<project> GOOGLE_GENAI_USE_VERTEXAI=true \
      PYTHONPATH=. python scripts/eval_one_consent_tool_selection.py <instruction_a.txt> <instruction_b.txt>
    AB_MODEL=gemini-3.7-flash ... to run against the model production pins.

Why this exists
---------------
The founder's own sentence, "can we request finance information from Sharu
Khan", was routed by One's previous instruction to `list_my_connections`, a
dead end, because that instruction never named `discover_person_information`
at all. Nothing in the test suite could have said so: tool selection is the
model's judgement and only a live call measures it.

Measured 2026-09-13 over 13 questions, four runs each, two models:
previous instruction 47/52 correct first tool, revised 52/52. Every miss on the
previous instruction was a discovery-shaped question or the trusted-people
case, the two things it never mapped to a tool. Expect run-to-run variance
even at temperature 0, and expect 429s from Vertex on back-to-back runs.

A/B: does the instruction change which tool One reaches for on consent questions?

Faithful to the runtime: tool declarations are built by ADK's own FunctionTool from
One's real tool functions, so the model sees exactly the docstrings it sees in
production. Temperature 0. One turn. The KPI is the FIRST tool the model calls.
"""

import os
import sys
import warnings
from pathlib import Path

warnings.filterwarnings("ignore")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from google import genai  # noqa: E402
from google.adk.tools import FunctionTool  # noqa: E402
from google.genai import types  # noqa: E402

from hushh_mcp.one_adk import action_tools as at  # noqa: E402
from hushh_mcp.one_adk import agent_tree as tree  # noqa: E402

TOOLS = [
    tree.ask_consent_agent,
    tree.ask_location_agent,
    at.discover_person_information,
    at.list_pending_information_requests,
    at.list_active_grants,
    at.list_my_outgoing_information_requests,
    at.propose_information_request,
    at.run_app_action,
    at.list_app_actions,
    at.list_my_connections,
    at.read_my_profile_status,
    at.get_current_time,
]
decls = []
for fn in TOOLS:
    d = FunctionTool(fn)._get_declaration()
    decls.append(
        types.FunctionDeclaration(name=d.name, description=d.description, parameters=d.parameters)
    )
tool = types.Tool(function_declarations=decls)

# question -> acceptable first tool(s). run_app_action counts when its action_id matches.
CASES = [
    ("is there anything waiting for me to approve", {"list_pending_information_requests"}),
    ("who can see my information right now", {"list_active_grants"}),
    ("what am I sharing with Sarah", {"list_active_grants"}),
    ("does anyone still have my address", {"list_active_grants"}),
    ("what did I ask Jhumma for", {"list_my_outgoing_information_requests"}),
    ("what could I ask Dev for", {"discover_person_information"}),
    (
        "can we request finance information from Sharu Khan",
        {"discover_person_information", "propose_information_request"},
    ),
    (
        "stop sharing my finances with my advisor",
        {"list_active_grants", "run_app_action:consent.revoke"},
    ),
    ("revoke what I gave Dev last week", {"list_active_grants", "run_app_action:consent.revoke"}),
    (
        "cancel the request I sent this morning",
        {"list_my_outgoing_information_requests", "run_app_action:consent.cancel_request"},
    ),
    (
        "say no to Sarah's request",
        {"list_pending_information_requests", "run_app_action:consent.deny"},
    ),
    ("how does sharing my information actually work", {None}),  # answer directly, no tool
    ("add Alice to my trusted people", {"ask_consent_agent"}),  # the ONE legit use of that tool
]

client = genai.Client(
    vertexai=True, project=os.environ["GENAI_GOOGLE_CLOUD_PROJECT"], location="global"
)
MODEL = os.environ.get("AB_MODEL", "gemini-3.8-flash")


def first_tool(instruction, q):
    r = client.models.generate_content(
        model=MODEL,
        contents=q,
        config=types.GenerateContentConfig(
            system_instruction=instruction, tools=[tool], temperature=0
        ),
    )
    for part in r.candidates[0].content.parts or []:
        fc = getattr(part, "function_call", None)
        if fc:
            if fc.name == "run_app_action":
                return f"run_app_action:{(fc.args or {}).get('action_id', '?')}"
            return fc.name
    return None


def score(label, instruction):
    hits = 0
    rows = []
    for q, ok in CASES:
        got = first_tool(instruction, q)
        good = (got in ok) or (got is None and None in ok)
        hits += good
        rows.append((good, q, got))
    return hits, rows


for label, path in (("CURRENT", sys.argv[1]), ("REVISED", sys.argv[2])):
    hits, rows = score(label, open(path).read())
    print(f"\n===== {label}: {hits}/{len(CASES)} correct first tool =====")
    for good, q, got in rows:
        print(f"  {'ok ' if good else 'BAD'}  {q:52} -> {got}")
