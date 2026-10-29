"""Same deterministic Responses sequence for all lanes, gated on real feedback."""

import json

from model_gateway import ModelGateway, wire

ANSWER = "HEPTA_REPRESENTATIVE_OK"


class ScriptGateway(ModelGateway):
    def begin_script(self, name, steps):
        with self.lock:
            self.case = {"name": name, "steps": steps, "calls": 0}

    def replay(self, case, body):
        index = case["calls"] - 1
        steps = case["steps"]
        if not 0 <= index <= len(steps):
            raise ValueError("replay cannot fabricate another response")
        feedback = [item for item in body.get("input", [])
                    if item.get("type") == "function_call_output"]
        if len(feedback) != index:
            raise ValueError("missing or duplicate real tool feedback")
        for number, (item, step) in enumerate(zip(feedback, steps)):
            if item.get("call_id") != f"call_{case['name']}_{number}":
                raise ValueError("original call identity changed")
            output = item.get("output")
            if isinstance(output, list):
                if len(output) != 1 or output[0].get("type") != "input_text":
                    raise ValueError("incomplete tool feedback")
                output = output[0]["text"]
            result = json.loads(output)
            if set(result) != {"exit_code", "stdout", "stderr"}:
                raise ValueError("unexpected tool result shape")
            if result["exit_code"] != step.get("exit", 0):
                raise ValueError("real tool did not reach expected exit state")
            if "stdout" in step and result["stdout"] != step["stdout"]:
                raise ValueError("real tool stdout disagrees with independent fixture")
            if step.get("stderr_contains") not in (None, "") and step["stderr_contains"] not in result["stderr"]:
                raise ValueError("expected observed failure was not returned")
        response_id = f"resp_{case['name']}_{index}"
        if index < len(steps):
            step = steps[index]
            item = {"type": "function_call", "id": f"fc_{case['name']}_{index}",
                    "call_id": f"call_{case['name']}_{index}", "status": "completed",
                    "name": step["tool"], "arguments": json.dumps(step["arguments"])}
        else:
            item = {"type": "message", "id": f"msg_{case['name']}", "role": "assistant",
                    "status": "completed", "content": [
                        {"type": "output_text", "text": ANSWER, "annotations": []}]}
        response = {"id": response_id, "object": "response", "created_at": 1,
                    "model": "qwen38-flash-next-uc", "status": "completed", "output": [item],
                    "usage": {"input_tokens": 10, "output_tokens": 5, "total_tokens": 15}}
        added = dict(item, status="in_progress")
        added["arguments" if index < len(steps) else "content"] = "" if index < len(steps) else []
        events = [{"type": "response.created", "response": dict(response, status="in_progress", output=[], usage=None)},
                  {"type": "response.output_item.added", "output_index": 0, "item": added}]
        if index < len(steps):
            events += [{"type": "response.function_call_arguments.delta", "item_id": item["id"],
                        "output_index": 0, "delta": item["arguments"]},
                       {"type": "response.function_call_arguments.done", "item_id": item["id"],
                        "output_index": 0, "arguments": item["arguments"]}]
        else:
            events += [{"type": "response.content_part.added", "item_id": item["id"], "output_index": 0,
                        "content_index": 0, "part": {"type": "output_text", "text": "", "annotations": []}},
                       {"type": "response.output_text.delta", "item_id": item["id"],
                        "output_index": 0, "content_index": 0, "delta": ANSWER},
                       {"type": "response.output_text.done", "item_id": item["id"],
                        "output_index": 0, "content_index": 0, "text": ANSWER},
                       {"type": "response.content_part.done", "item_id": item["id"], "output_index": 0,
                        "content_index": 0, "part": item["content"][0]}]
        events += [{"type": "response.output_item.done", "output_index": 0, "item": item},
                   {"type": "response.completed", "response": response}]
        for number, event in enumerate(events):
            event["sequence_number"] = number
        return b"".join(b"event: " + event["type"].encode() + b"\ndata: " + wire(event) + b"\n\n"
                        for event in events), response
