from app.core.context_schema import SharedContext


def score_answer_correctness(final_answer: str, expected_keywords: list[str]) -> dict:
    answer = (final_answer or "").lower()
    if not expected_keywords:
        return {"score": 1.0, "justification": "No expected keywords were supplied."}
    hits = [kw for kw in expected_keywords if kw.lower() in answer]
    return {
        "score": len(hits) / len(expected_keywords),
        "justification": f"Matched {len(hits)} of {len(expected_keywords)} expected keywords: {hits}.",
    }


def score_citation_accuracy(provenance_map: dict, retrieval_output: dict) -> dict:
    if not provenance_map:
        return {"score": 0.0, "justification": "No provenance map was produced."}
    citations = retrieval_output.get("citations", {}) if retrieval_output else {}
    valid_sources = {"retrieval", "decomposition", "critique", "synthesis", "chunk_1", "chunk_2"}
    valid = 0
    for source in provenance_map.values():
        text = str(source).lower()
        if any(marker in text for marker in valid_sources) or source in citations.values():
            valid += 1
    return {
        "score": valid / max(len(provenance_map), 1),
        "justification": f"{valid} of {len(provenance_map)} provenance entries reference known agents or chunks.",
    }


def score_contradiction_resolution(synthesis_output: dict, critique_output: dict) -> dict:
    flagged = [c for c in critique_output.get("claim_scores", []) if c.get("flagged")] if critique_output else []
    resolutions = synthesis_output.get("contradiction_resolutions", []) if synthesis_output else []
    if not flagged:
        return {"score": 1.0, "justification": "No flagged contradictions required resolution."}
    return {
        "score": min(len(resolutions) / len(flagged), 1.0),
        "justification": f"Resolved {len(resolutions)} of {len(flagged)} flagged claims.",
    }


def score_tool_efficiency(tool_call_log: list, expected_max_tool_calls: int = 6) -> dict:
    count = len(tool_call_log or [])
    if count <= expected_max_tool_calls:
        score = 1.0
    else:
        score = max(0.0, 1.0 - ((count - expected_max_tool_calls) / expected_max_tool_calls))
    return {"score": score, "justification": f"Used {count} tool calls; expected at most {expected_max_tool_calls}."}


def score_budget_compliance(budget_states: dict) -> dict:
    states = budget_states or {}
    if not states:
        return {"score": 0.0, "justification": "No budget states were registered."}
    violations = []
    for state in states.values():
        violations.extend(state.get("violations", []) if isinstance(state, dict) else state.violations)
    return {
        "score": 1.0 if not violations else max(0.0, 1.0 - 0.2 * len(violations)),
        "justification": f"{len(violations)} budget violations recorded.",
    }


def score_critique_agreement(critique_output: dict, synthesis_output: dict) -> dict:
    flagged = [c.get("claim_text", "") for c in critique_output.get("claim_scores", []) if c.get("flagged")] if critique_output else []
    final_answer = (synthesis_output.get("final_answer", "") if synthesis_output else "").lower()
    unresolved = [claim for claim in flagged if claim and claim.lower() in final_answer]
    if not flagged:
        return {"score": 1.0, "justification": "No critique flags were present."}
    return {
        "score": 1.0 - (len(unresolved) / len(flagged)),
        "justification": f"{len(unresolved)} of {len(flagged)} flagged claims appear unresolved in the final answer.",
    }


def score_test_case(ctx: SharedContext, expected_keywords: list[str]) -> dict:
    retrieval_output = ctx.agent_outputs.get("retrieval")
    critique_output = ctx.agent_outputs.get("critique")
    synthesis_output = ctx.agent_outputs.get("synthesis")

    retrieval_data = retrieval_output.output if retrieval_output else {}
    critique_data = critique_output.output if critique_output else {}
    synthesis_data = synthesis_output.output if synthesis_output else {}

    scores = {
        "answer_correctness": score_answer_correctness(ctx.final_answer or "", expected_keywords),
        "citation_accuracy": score_citation_accuracy(ctx.provenance_map, retrieval_data),
        "contradiction_resolution": score_contradiction_resolution(synthesis_data, critique_data),
        "tool_efficiency": score_tool_efficiency([t.model_dump(mode="json") for t in ctx.tool_call_log]),
        "budget_compliance": score_budget_compliance(ctx.model_dump(mode="json")["budget_states"]),
        "critique_agreement": score_critique_agreement(critique_data, synthesis_data),
    }
    scores["overall_average"] = sum(item["score"] for item in scores.values()) / len(scores)
    return scores

