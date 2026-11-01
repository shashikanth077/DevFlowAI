"""LangGraph StateGraph definition for the DevFlow AI workflow.

    requirement_analysis -> repository_analysis -> architecture_design -> task_planning
        -> {frontend_development || backend_development} -> development_join
        -> execution_approval (human gate) -> testing
              tests failed  -> responsible development agent(s)  (retry loop)
              max retries   -> max_retries_exceeded -> END
        -> code_review
              review failed -> responsible development agent(s)  (retry loop)
        -> release_approval (human gate) -> github_release -> END

Every edge also routes to END when the workflow is cancelled or failed.
"""

from __future__ import annotations

from langgraph.graph import END, START, StateGraph

from app.orchestration.nodes import build_nodes
from app.orchestration.routing import (
    DEV_NODES,
    after_development,
    continue_or_end,
    route_after_review,
    route_after_tests,
    route_to_development,
)
from app.orchestration.runtime import WorkflowRuntime
from app.orchestration.state import ProjectState

DEV_TARGETS = [*DEV_NODES.values(), END]


def build_graph(runtime: WorkflowRuntime) -> StateGraph:
    nodes = build_nodes(runtime)
    graph = StateGraph(ProjectState)
    for name, fn in nodes.items():
        graph.add_node(name, fn)

    graph.add_edge(START, "requirement_analysis")
    graph.add_conditional_edges("requirement_analysis", continue_or_end("repository_analysis"),
                                ["repository_analysis", END])
    graph.add_conditional_edges("repository_analysis", continue_or_end("architecture_design"),
                                ["architecture_design", END])
    graph.add_conditional_edges("architecture_design", continue_or_end("task_planning"), ["task_planning", END])
    graph.add_conditional_edges("task_planning", route_to_development, DEV_TARGETS)
    graph.add_conditional_edges("frontend_development", after_development("frontend"),
                                ["backend_development", "development_join", END])
    graph.add_conditional_edges("backend_development", after_development("backend"),
                                ["frontend_development", "development_join", END])
    graph.add_conditional_edges("development_join", continue_or_end("execution_approval"),
                                ["execution_approval", END])
    graph.add_conditional_edges("execution_approval", continue_or_end("testing"), ["testing", END])
    graph.add_conditional_edges("testing", route_after_tests, [*DEV_TARGETS, "code_review", "max_retries_exceeded"])
    graph.add_conditional_edges("code_review", route_after_review,
                                [*DEV_TARGETS, "release_approval", "max_retries_exceeded"])
    graph.add_edge("max_retries_exceeded", END)
    graph.add_conditional_edges("release_approval", continue_or_end("github_release"), ["github_release", END])
    graph.add_edge("github_release", END)
    return graph


def compile_graph(runtime: WorkflowRuntime, checkpointer):
    return build_graph(runtime).compile(checkpointer=checkpointer)
