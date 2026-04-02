from langgraph.graph import StateGraph, END
from typing import TypedDict, Union

class GraphState(TypedDict):
    alerts: list
    processed: list
    resolutions: list
    generated: list
    splunk_results: Union[list, None]
    verification_status: str
    verification_message: str
    verification_data: list
    next: str
    execution_summary: list  # Store node execution summaries
    summary_id: int        # Alert ID for linking to database summaries
    alert_id: int  # Alert ID from request body

    # Task agent tracking fields
    task_agent_execution_id: int
    task_agent_alert_id: int
    task_agent_start_time: str
    workflow_type: str  # 'splunk'

    # Analysis node results
    error_analysis: dict
    troubleshooting: dict
    fix_suggestions: dict

from app.nodes.read_from_db_node import read_from_db_node
from app.nodes.fetch_remediation_node import fetch_resolution_node
from app.nodes.generate_remediation_node import generate_remediation_node
from app.nodes.send_email_node import send_email
from app.nodes.examine_error_node import examine_error_node
from app.nodes.troubleshoot_node import troubleshoot_node
from app.nodes.suggestions_node import suggestions_node

# Import task agent finalization functions
from app.utility.summary_tracker import finalize_workflow_and_send_email, should_finalize_workflow


def splunk_workflow_finalization_node(state):
    """
    Finalization node for Splunk workflow that ensures execution data is saved
    and sends the completion email.

    Three-phase approach:
      Phase 1 — Capture a placeholder for finalize_workflow so total_steps is correct.
      Phase 2 — finalize_workflow_and_send_email builds + persists the full rich record.
      Phase 3 — Read-patch-write: fix ONLY the finalize_workflow node card in DB
                with the real email outcome, preserving all existing rich data.
    """
    from app.utility.summary_tracker import capture_node_execution

    print("🔄 Starting Splunk workflow finalization...")

    alerts = state.get("alerts", [])

    print(f"DEBUG [finalize] alerts count: {len(alerts)}")
    if alerts:
        print(f"DEBUG [finalize] Alert[0] source: '{alerts[0].get('source', 'KEY_NOT_FOUND')}'")
    print(f"DEBUG [finalize] execution_summary count: {len(state.get('execution_summary', []))}")
    for i, node in enumerate(state.get('execution_summary', [])):
        print(f"DEBUG [finalize]   step[{i}]: node={node.get('node_name')}, status={node.get('status')}")

    state["workflow_type"] = "splunk"

    # ── Phase 1: Capture placeholder so finalize_workflow is counted in total_steps ──
    state = capture_node_execution(
        state, "finalize_workflow",
        result="Splunk workflow finalization in progress",
        status="success",
    )

    # ── Phase 2: Build rich summary + persist + send email ──
    # finalize_workflow_and_send_email reads execution_summary (which now includes
    # finalize_workflow), builds the full rich task_agent_full_result with correct
    # total_steps, confidence_score, llm_analysis, execution_details etc., persists
    # everything via a single update_task_agent_execution call, and sends email.
    final_state, email_ok, user_message = finalize_workflow_and_send_email(state)
    status_str = "success" if email_ok else "error"
    result_message = "Splunk workflow completed | " + user_message

    # ── Phase 3: Read-patch-write — fix finalize_workflow node card only ──
    # Read the existing DB record (with full rich data), patch ONLY the
    # finalize_workflow node entry with the real email outcome + wrapped format,
    # then write back preserving all existing task_agent_full_result and confidence_score.
    from store.db import get_task_agent_execution_summary, update_task_agent_execution
    alert_id = final_state.get("task_agent_alert_id")

    if alert_id:
        existing = get_task_agent_execution_summary(alert_id)
        if existing:
            nodes = existing.get("task_agent_execution_nodes", [])
            full_result = existing.get("task_agent_full_result", {})
            confidence = existing.get("confidence_score")
            db_status = existing.get("task_agent_status", "completed")

            for node in nodes:
                if node.get("node_name") == "finalize_workflow":
                    node["status"] = status_str
                    node["result_summary"] = f"finalize_workflow completed: {result_message}"
                    node["full_result"] = {
                        "execution_result": result_message,
                        "verification_status": "completed",
                    }
                    break

            execution_id = final_state.get("task_agent_execution_id")
            if execution_id:
                update_task_agent_execution(
                    execution_id, nodes, full_result, db_status, confidence
                )
                print(f"DEBUG [finalize] Patched finalize_workflow node card in DB")

    print(f"✅ Splunk workflow finalization completed with status={status_str}: {user_message}")
    return final_state


def build_graph():
    graph = StateGraph(GraphState)

    # Add nodes — Splunk workflow only
    graph.add_node("read_from_db", read_from_db_node)
    graph.add_node("fetch_resolution", fetch_resolution_node)
    graph.add_node("generate_resolution", generate_remediation_node)
    graph.add_node("send_email", send_email)

    # Analysis nodes (always run after resolution is known)
    graph.add_node("examine_the_error",      examine_error_node)
    graph.add_node("troubleshoot_the_issue", troubleshoot_node)
    graph.add_node("suggestions_for_fix",    suggestions_node)

    graph.add_node("finalize_workflow", splunk_workflow_finalization_node)

    graph.set_entry_point("read_from_db")

    # read_from_db → fetch_resolution
    graph.add_edge("read_from_db", "fetch_resolution")

    # fetch_resolution → router (generate or examine_the_error)
    graph.add_conditional_edges("fetch_resolution", decide_resolution_path)

    # generate_resolution → router (examine_the_error once resolutions exist)
    graph.add_conditional_edges("generate_resolution", decide_resolution_path)

    # Fixed analysis chain — always runs after resolution is resolved
    graph.add_edge("examine_the_error",      "troubleshoot_the_issue")
    graph.add_edge("troubleshoot_the_issue", "suggestions_for_fix")
    graph.add_edge("suggestions_for_fix",    "finalize_workflow")

    # Finalization ends the workflow
    graph.add_edge("finalize_workflow", END)

    return graph


def decide_resolution_path(state: GraphState) -> str:
    """
    Decide the next node based on resolution availability.

    Routing priority:
      0. No resolutions yet and generation needed  → generate_resolution
      1. Resolutions available (DB or generated)   → examine_the_error
      2. Default (no resolutions, none needed)     → examine_the_error
    """
    resolutions = state.get("resolutions", [])
    processed_alerts = state.get("processed", [])
    alerts = state.get("alerts", [])

    # ─── DEBUG LOGGING ───
    print(f"[Router] ========== decide_resolution_path ENTRY ==========")
    print(f"[Router] Number of alerts: {len(alerts)}")
    print(f"[Router] Number of resolutions: {len(resolutions)}")
    print(f"[Router] Number of processed_alerts: {len(processed_alerts)}")

    if alerts and len(alerts) > 0:
        a0 = alerts[0]
        print(f"[Router] Alert[0] id: {a0.get('id')}")
        print(f"[Router] Alert[0] source: '{a0.get('source')}'")
        print(f"[Router] Alert[0] classification: '{a0.get('classification')}'")
        print(f"[Router] Alert[0] ticket_id: '{a0.get('ticket_id')}'")
    else:
        print(f"[Router] WARNING: alerts list is empty!")

    if resolutions:
        r0 = resolutions[0]
        print(f"[Router] Resolution[0] action_type: '{r0.get('action_type')}'")
        print(f"[Router] Resolution[0] description (first 100): '{str(r0.get('description', ''))[:100]}'")

    # Check if any alert still needs resolution generation
    needs_generation = any(
        alert.get("resolution_source") == "needs_generation"
        for alert in processed_alerts
    )

    # ─── PRIORITY 0: Generate resolution if none exists yet ───
    if not resolutions and needs_generation:
        print(f"[Router] No resolutions found — routing to generate_resolution")
        return "generate_resolution"

    # ─── PRIORITY 1: Resolution found (DB or generated) → start analysis chain ───
    if resolutions:
        print(f"[Router] Resolution(s) found — routing to examine_the_error")
        return "examine_the_error"

    # ─── PRIORITY 2: No resolutions, no generation needed → start analysis chain ───
    print(f"[Router] No resolutions and no generation needed — routing to examine_the_error")
    return "examine_the_error"
