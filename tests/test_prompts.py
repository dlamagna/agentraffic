"""Smoke tests for prompt template formatting — no GPU or network required."""

import pytest
from agents.agent_a.prompts import (
    EXPERT_RECRUITMENT_PROMPT,
    HORIZONTAL_DISCUSSION_PROMPT,
    FULL_MESH_DISCUSSION_PROMPT,
    VERTICAL_SOLVER_PROMPT,
    VERTICAL_REVIEWER_PROMPT,
    EXECUTION_PROMPT,
    EVALUATION_PROMPT,
    FINAL_SYNTHESIS_PROMPT,
)


def test_expert_recruitment_prompt_format():
    result = EXPERT_RECRUITMENT_PROMPT.format(
        task="Explain gradient descent.",
        feedback_context="",
        agent_count_instruction="",
        force_structure_instruction="",
        agent_count_guidance="Choose 2–4 agents.",
        structure_guidance="Use horizontal structure.",
        agent_count_json_constraint="",
    )
    assert "Explain gradient descent." in result
    assert "communication_structure" in result


def test_horizontal_discussion_prompt_format():
    result = HORIZONTAL_DISCUSSION_PROMPT.format(
        role="critic",
        contract="Review the proposed solution critically.",
        task="Explain gradient descent.",
        discussion_history="Agent planner: Start with the objective function.",
        round_num=1,
    )
    assert "critic" in result
    assert "round_num" not in result  # placeholder must be substituted


def test_full_mesh_discussion_prompt_format():
    result = FULL_MESH_DISCUSSION_PROMPT.format(
        sender_role="planner",
        sender_contract="Plan the approach.",
        task="Explain TCP vs UDP.",
        receiver_role="critic",
        discussion_history="",
        round_num=1,
    )
    assert "planner" in result
    assert "critic" in result


def test_vertical_solver_prompt_format():
    result = VERTICAL_SOLVER_PROMPT.format(
        contract="Propose a detailed solution.",
        task="Explain backpropagation.",
        previous_proposal="",
        critiques="",
    )
    assert "Explain backpropagation." in result


def test_evaluation_prompt_substitutes_threshold():
    result = EVALUATION_PROMPT.format(
        task="Explain backpropagation.",
        results="Agent outputs here.",
        iteration=1,
        max_iterations=3,
        success_threshold=70,
    )
    assert "70" in result
    assert "score" in result


def test_no_unformatted_placeholders_in_final_synthesis():
    result = FINAL_SYNTHESIS_PROMPT.format(
        task="Some task.",
        iteration_summary="Round 1: ...",
        results="Final results.",
        evaluation="Score: 85",
    )
    assert "{" not in result
