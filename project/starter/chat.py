#!/usr/bin/env python3
"""Chat with your support chatbot from the terminal.

    python chat.py

Every run starts ONE conversation (one `runtimeSessionId`). The harness is
stateful: as long as you reuse the same session id, it remembers the whole
conversation — that is what lets it collect bug details over several turns.
Start the script again to get a fresh conversation.

The script attaches your AgentCore Gateway to each invoke, so the model can
call the create_bug_report tool. When it does, you'll see a line like:

    [tool call] bugreports___create_bug_report

Type your message and press Enter. Type 'quit' (or Ctrl-C) to exit.
"""

import argparse
import json
import re
import sys
import uuid
from pathlib import Path

import boto3
from botocore.config import Config
from botocore.eventstream import EventStream


def event_stream(response):
    """Locate the streaming part of the invoke_harness response."""
    for value in response.values():
        if isinstance(value, EventStream):
            return value
    raise RuntimeError(f"No event stream in response: {list(response)}")


def invoke(rt, config, session_id, messages, verbose=False, tools_enabled=True):
    """Send one user message and print only the customer-facing reply.

    Returns the assistant's final text. Tool calls and tool results are
    handled server-side by the harness. Intermediate model reasoning is not
    customer-facing, so it is collected rather than streamed to the terminal.
    """
    tools = []
    if tools_enabled:
        tools = [{
            "type": "agentcore_gateway",
            "name": "support_gateway",
            "config": {"agentCoreGateway": {"gatewayArn": config["gateway_arn"]}},
        }]

    response = rt.invoke_harness(
        harnessArn=config["harness_arn"],
        runtimeSessionId=session_id,
        # Pin the model on every invoke as well (belt and suspenders —
        # create_harness.py already pinned it on the harness).
        model={"bedrockModelConfig": {"modelId": config.get("model_id", "us.amazon.nova-pro-v1:0")}},
        # Attach the gateway so the model can use create_bug_report.
        tools=tools,
        # Send the full transcript explicitly. A runtime session identifies
        # the conversation, but the harness does not reliably replay prior
        # turns into every model invocation for us.
        messages=messages,
    )

    texts = []      # completed assistant messages
    buffer = []     # text of the message currently streaming
    tool_calls = []
    for event in event_stream(response):
        if verbose:
            print(f"\n[event] {json.dumps(event, default=str)}", file=sys.stderr)
        if "contentBlockStart" in event:
            tool_use = event["contentBlockStart"].get("start", {}).get("toolUse")
            if tool_use:
                tool_calls.append(tool_use.get("name", "?"))
        elif "contentBlockDelta" in event:
            delta = event["contentBlockDelta"].get("delta", {})
            if "text" in delta:
                buffer.append(delta["text"])
        elif "messageStop" in event:
            if buffer:
                texts.append("".join(buffer))
                buffer = []
    if buffer:
        texts.append("".join(buffer))

    final_text = texts[-1] if texts else ""
    final_text = re.sub(
        r"<(?:thinking|analysis|reasoning)>.*?</(?:thinking|analysis|reasoning)>",
        "",
        final_text,
        flags=re.IGNORECASE | re.DOTALL,
    ).strip()

    for tool_name in tool_calls:
        print(f"\n[tool call] {tool_name}")
    print(final_text)
    return final_text


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default="agentcore_config.json",
                        help="Config file written by the setup scripts.")
    parser.add_argument("--verbose", action="store_true",
                        help="Print every raw stream event (for debugging).")
    args = parser.parse_args()

    config = json.loads(Path(args.config).read_text(encoding="utf-8"))
    if "harness_arn" not in config:
        sys.exit("No harness in config yet — run create_harness.py first.")

    # Session ids must be at least 33 characters — a UUID plus a suffix.
    session_id = f"{uuid.uuid4()}-support-chat"

    rt = boto3.client(
        "bedrock-agentcore",
        region_name=config["region"],
        # Tool-using turns can take a while; don't let boto3 time out.
        config=Config(read_timeout=300, retries={"max_attempts": 1}),
    )

    print(f"Connected to harness {config.get('harness_name', '?')} "
          f"(session {session_id}).")
    print("Type a message, or 'quit' to exit.\n")

    messages = []
    bug_fields = {}
    awaiting_bug_field = None

    while True:
        try:
            user_text = input("you> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not user_text:
            continue
        if user_text.lower() in ("quit", "exit"):
            break
        messages.append({"role": "user", "content": [{"text": user_text}]})

        # Enforce the bug intake state machine in the application layer. This
        # keeps the ticketing tool unavailable until all three required fields
        # have been collected, even if the model tries to act prematurely.
        normalized = user_text.strip().lower()
        if awaiting_bug_field == "description":
            bug_fields["description"] = user_text
            reply = "What steps can we follow to reproduce the issue?"
            awaiting_bug_field = "stepsToReproduce"
        elif awaiting_bug_field == "stepsToReproduce":
            bug_fields["stepsToReproduce"] = user_text
            reply = ("What environment did this occur in? Please include "
                     "the browser, operating system, and device.")
            awaiting_bug_field = "environment"
        elif awaiting_bug_field is None and normalized in {
            "broken", "it is broken", "it's broken"
        }:
            reply = "Please describe what is broken and what happened."
            awaiting_bug_field = "description"
        elif awaiting_bug_field is None and re.search(
            r"\b(crash(?:es|ed|ing)?|broken|not working|error|bug|freeze[sd]?)\b",
            normalized,
        ):
            bug_fields["description"] = user_text
            reply = "What steps can we follow to reproduce the issue?"
            awaiting_bug_field = "stepsToReproduce"
        else:
            reply = None

        if reply is not None:
            print(f"bot> {reply}\n")
            messages.append({
                "role": "assistant",
                "content": [{"text": reply}],
            })
            continue

        if awaiting_bug_field == "environment":
            bug_fields["environment"] = user_text
            awaiting_bug_field = None

        print("bot> ", end="", flush=True)
        assistant_text = invoke(
            rt, config, session_id, messages, verbose=args.verbose
        )
        if assistant_text:
            messages.append({
                "role": "assistant",
                "content": [{"text": assistant_text}],
            })
        print()


if __name__ == "__main__":
    main()
